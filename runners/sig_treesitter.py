#!/usr/bin/env python3
"""sig_treesitter.py — firma implementada vs contrato para lenguajes NO-Python via tree-sitter.

Espejo multi-lenguaje de sig_check.py (Python/AST): compara nombre de funcion + nombres de
parametros EN ORDEN (tipos, defaults y anotaciones se ignoran). Dependencia OPCIONAL (patron de
metrics_treesitter): sin tree_sitter o sin la gramatica del lenguaje, parse_signature devuelve
None y check_signature_src un mensaje de error — nunca lanzan.

Tecnica de completado del snippet: una firma suelta del contrato ("function f(a: string)") no
siempre es una declaracion completa para tree-sitter (falta el cuerpo). Antes de parsear se
prueban variantes COMPLETADAS deterministas por lenguaje (apendear " {}"; PHP ademas con prefijo
"<?php ") y se usa la primera cuyo arbol contenga una declaracion de funcion con nombre y
parametros extraibles. Los nodos ERROR residuales del arbol se toleran si la declaracion esta
presente (extraccion tolerante, no exige arbol 100% limpio).

Reutiliza SPECS de metrics_treesitter (mapas de nodos por lenguaje): un solo mapa, sin duplicar.
"""

# Tipos de nodo que actuan como identificador de un parametro segun la gramatica
# (identifier: TS/Go/Rust/Java/C#; variable_name/name: PHP).
_IDENT_TYPES = ("identifier", "variable_name", "name", "field_identifier")


def _load_spec(language):
    """(spec, parser) del lenguaje, o None si falta tree_sitter, el LangSpec o la gramatica."""
    try:
        from tree_sitter import Language, Parser
        from metrics_treesitter import SPECS
    except ImportError:
        return None
    lang = (language or "").lower()
    for s in SPECS:
        if s.language != lang:
            continue
        try:
            return s, Parser(Language(s.grammar_loader()))
        except Exception:
            return None
    return None


def _walk(node):
    """Recorrido preorder (orden de fuente) iterativo del arbol tree-sitter."""
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _candidates(sig, lang):
    """Variantes de completado minimo del snippet de firma, en orden de preferencia."""
    s = str(sig).strip().rstrip(";").strip()
    if lang == "php":
        return ("<?php " + s + " {}", "<?php " + s)
    return (s + " {}", s)


def _names_of_param(node):
    """Nombres declarados por UN nodo parametro (lista: Go agrupa varios nombres por nodo)."""
    if node.type in ("parameter_declaration", "variadic_parameter_declaration"):  # Go
        names = [c.text.decode("utf-8", "replace")
                 for c in node.named_children if c.type == "identifier"]
        if names:
            return names
    if node.type in _IDENT_TYPES:
        return [node.text.decode("utf-8", "replace")]
    for field in ("name", "pattern"):  # name: Java/C#/PHP · pattern: TS/JS/Rust
        val = node.child_by_field_name(field)
        if val is not None:
            return [val.text.decode("utf-8", "replace")]
    return []


def _param_names(params_node):
    """Nombres de parametros EN ORDEN (sin tipos/defaults). Go: f(a, b int) -> [a, b]."""
    if params_node is None:
        return []
    out = []
    for child in params_node.named_children:
        out.extend(_names_of_param(child))
    return out


def _decl_info(fn, spec):
    """{"name", "params"} de una declaracion de funcion, o None si no expone nombre."""
    nm = fn.child_by_field_name(spec.name_field)
    if nm is None:
        return None
    params = _param_names(fn.child_by_field_name(spec.params_field))
    return {"name": nm.text.decode("utf-8", "replace"), "params": params}


def _first_decl(tree, spec):
    """Primera declaracion de funcion del arbol con nombre extraible, o None."""
    for n in _walk(tree.root_node):
        if n.type not in spec.function_nodes:
            continue
        info = _decl_info(n, spec)
        if info is not None:
            return info
    return None


def _parse_candidate(text, parser, spec):
    """Parsea un candidato de snippet y extrae la primera declaracion, o None."""
    try:
        tree = parser.parse(text.encode("utf-8"))
    except Exception:
        return None
    return _first_decl(tree, spec)


def parse_signature(signature, language):
    """{"name": str, "params": [str, ...]} de una firma, o None.

    None si la gramatica del lenguaje no esta instalada (dep opcional) o el snippet no parsea
    como declaracion de funcion. `params` en orden, solo nombres (sin tipos ni defaults).
    Nunca lanza."""
    loaded = _load_spec(language)
    if loaded is None:
        return None
    spec, parser = loaded
    for cand in _candidates(signature, spec.language):
        info = _parse_candidate(cand, parser, spec)
        if info is not None:
            return info
    return None


def _has_name(n, spec, fn_name):
    """True si la declaracion `n` se llama `fn_name`."""
    nm = n.child_by_field_name(spec.name_field)
    return nm is not None and nm.text.decode("utf-8", "replace") == fn_name


def _find_impl(tree, spec, fn_name, target_line):
    """Nodo de la funcion `fn_name`: con target_line, la de esa linea; sin el, la primera en
    orden de fuente (preorder). None si no hay match (espejo de sig_check._find_function)."""
    for n in _walk(tree.root_node):
        if n.type not in spec.function_nodes or not _has_name(n, spec, fn_name):
            continue
        if target_line is None:
            return n
        if n.start_point[0] + 1 == target_line:
            return n
    return None


def check_signature_src(source, fn_name, expected_signature, language, target_line=None):
    """'' si la firma implementada en `source` coincide con la esperada (nombre + nombres de
    parametros en orden); mensaje ASCII con el desajuste en caso contrario.

    Espejo de sig_check.signature_mismatch para lenguajes no-Python. `target_line` (opcional)
    desambigua funciones homonimas (la def de esa linea)."""
    expected = parse_signature(expected_signature, language)
    if expected is None:
        return "expected_signature parse failed (grammar not available or signature invalid)"
    loaded = _load_spec(language)
    if loaded is None:
        return "grammar not available for language: " + str(language)
    spec, parser = loaded
    impl = _find_impl(parser.parse(source.encode("utf-8")), spec, fn_name, target_line)
    if impl is None:
        return "function not found: " + fn_name
    if expected["name"] != fn_name:
        return "function name mismatch: " + fn_name + " != " + expected["name"]
    impl_params = _param_names(impl.child_by_field_name(spec.params_field))
    if impl_params != expected["params"]:
        return "param mismatch: " + str(impl_params) + " != " + str(expected["params"])
    return ""
