"""metrics_treesitter.py — backend UNIVERSAL de métricas vía tree-sitter (dependencia OPCIONAL).

Decisión #7: en vez de un runner nativo por lenguaje, un solo backend que calcula las cuatro
métricas sobre el AST de tree-sitter usando un MAPA de tipos de nodo por gramática (`LangSpec`).
Añadir un lenguaje = añadir su `LangSpec` + registrar (si su gramática está instalada).

Dependencia opcional: si `tree_sitter` (y la gramática del lenguaje) no están instalados, este
módulo no registra nada y el resto de ccdd-gate sigue funcionando con el backend Python nativo.
No rompe el "zero-dep salvo pyyaml" del camino por defecto.

Las métricas son las MISMAS (definición neutral en metrics_backends) y deben pasar la suite de
conformancia (#8). Determinista, sin LLM.
"""
import metrics_backends as _mb


class LangSpec:
    """Mapa de tipos de nodo tree-sitter de una gramática a los conceptos de las métricas.

    function_nodes : nodos que cuentan como "una función" (se mide cada uno)
    decision_nodes : suman +1 a ciclomática (if/for/while/do/ternario/catch/cada rama de switch)
    nest_nodes     : incrementan la profundidad de anidamiento (bloques que anidan)
    boolop_node    : tipo de nodo de operación binaria; cada operador en boolop_ops suma +1
    boolop_ops     : operadores booleanos que cuentan (&&, ||)
    params_field   : nombre del campo que contiene la lista de parámetros de la función
    name_field     : nombre del campo con el identificador de la función
    anon_name_parents : {tipo_nodo_ancestro: campo} para nombrar funciones anónimas (closures/
                        func literals): se sube por los ancestros y, si uno coincide, se extrae
                        el identificador de ese campo (directo o primer identificador hijo).
    params_counter   : hook OPCIONAL (lenguaje, nodo parameters) -> int. Si es None (default),
                        el conteo de parámetros es len(named_children) del nodo parameters —
                        correcto para lenguajes donde cada parámetro es su propio nodo
                        (TS/JS/Rust: un `parameter`/`formal_parameter` por parámetro). Si se
                        provee, se usa en su lugar: necesario cuando una gramática agrupa varios
                        nombres que comparten tipo en un único nodo declaración (p. ej. Go:
                        `func f(a, b int)` es UN `parameter_declaration` con dos `identifier`
                        hijos, no dos nodos). El default intacto garantiza cero cambio para el
                        resto de los backends.
    """
    def __init__(self, language, extensions, grammar_loader, function_nodes, decision_nodes,
                 nest_nodes, boolop_node, boolop_ops, params_field="parameters", name_field="name",
                 anon_name_parents=None, params_counter=None):
        self.language = language
        self.extensions = extensions
        self.grammar_loader = grammar_loader
        self.function_nodes = set(function_nodes)
        self.decision_nodes = set(decision_nodes)
        self.nest_nodes = set(nest_nodes)
        self.boolop_node = boolop_node
        self.boolop_ops = set(boolop_ops)
        self.params_field = params_field
        self.name_field = name_field
        self.anon_name_parents = anon_name_parents or {}
        self.params_counter = params_counter


# --- gramáticas concretas ---------------------------------------------------------------------
def _ts_loader():
    import tree_sitter_typescript as tsts
    return tsts.language_typescript()


def _tsx_loader():
    import tree_sitter_typescript as tsts
    return tsts.language_tsx()


def _rust_loader():
    import tree_sitter_rust as tsrust
    return tsrust.language()


def _go_loader():
    import tree_sitter_go as tsgo
    return tsgo.language()


# Nodos comunes a TS/JS (la gramática typescript de tree-sitter cubre ambos sintácticamente).
_JSTS_FUNCS = ("function_declaration", "function_expression", "arrow_function",
               "method_definition", "generator_function", "generator_function_declaration")
_JSTS_DECISION = ("if_statement", "for_statement", "for_in_statement", "while_statement",
                  "do_statement", "ternary_expression", "catch_clause",
                  "switch_case", "switch_default")
# try_statement anida pero NO es decisión (espejo de Python: Try anida, ExceptHandler decide).
_JSTS_NEST = ("if_statement", "for_statement", "for_in_statement", "while_statement",
              "do_statement", "try_statement")
# TS: las anónimas (arrow/function_expression) cuelgan de un variable_declarator / pair / campo.
_JSTS_ANON = {"variable_declarator": "name", "pair": "key", "public_field_definition": "name"}

# --- Rust ----------------------------------------------------------------------
# function_item cubre funciones libres Y métodos (los métodos son function_item dentro de impl).
# closure_expression es la función anónima de Rust (análogo a arrow_function de TS).
# Decisiones: if/while/for/loop son *_expression; cada rama de match es un match_arm (NO el
# match_expression, que por sí solo no suma — espejo de switch_case/switch_default en TS).
# unsafe_block / async_block anidan SIN ser decisión: son el análogo de `with`/`try` de Python
# (bloques de ámbito sin bifurcación de control).
_RUST_FUNCS = ("function_item", "closure_expression")
_RUST_DECISION = ("if_expression", "for_expression", "while_expression", "loop_expression",
                  "match_arm")
_RUST_NEST = ("if_expression", "for_expression", "while_expression", "loop_expression",
              "unsafe_block", "async_block")
# Cierre anónimo: `let f = |a| a;` → el closure cuelga de un let_declaration (campo "pattern").
_RUST_ANON = {"let_declaration": "pattern"}

# --- Go ------------------------------------------------------------------------
# function_declaration (fn libre), method_declaration (método con receiver) y func_literal
# (función anónima, análogo a arrow_function de TS).
# Decisiones: if/for (Go usa `for` para for/while/range) y cada case explícito de switch/type
# switch/select (expression_case, type_case, communication_case). default_case NO suma: es la
# rama por defecto (camino base), modelo "ramas − 1" — análogo a contar solo los case explícitos.
# select_statement anida SIN ser decisión: un `select { default: … }` tiene un único camino (sin
# bifurcación) y es el análogo de `with`/`try` de Python (Go carece de try/with/unsafe-block).
# switch/type_switch NO están en nest: así switch_case da nesting_depth 0 (espejo de TS).
_GO_FUNCS = ("function_declaration", "method_declaration", "func_literal")
_GO_DECISION = ("if_statement", "for_statement", "expression_case", "type_case",
                "communication_case")
_GO_NEST = ("if_statement", "for_statement", "select_statement")
# Func literal anónima: `f := func(){}` (short_var_declaration, campo "left" → lista con `f`)
# o `var g = func(){}` (var_spec, campo "name" → `g`).
_GO_ANON = {"short_var_declaration": "left", "var_spec": "name"}


def _go_param_count(params_node):
    """Cuenta parámetros Go por NOMBRE declarado, no por declaración.

    Go permite agrupar parámetros que comparten tipo: `func f(a, b int)` es UN solo nodo
    `parameter_declaration` con dos hijos `identifier` (a, b) seguidos del tipo. El contador
    genérico (len de named_children del `parameter_list`) reportaría 1, evadiendo el gate de
    aridad (params <= 5): `func f(a, b, c, d, e, f int)` contaría 1 en vez de 6.

    Aquí recorremos cada declaración dentro del `parameter_list` y sumamos:
      - `parameter_declaration`: cuenta de sus hijos `identifier` directos (los nombres; el
        tipo es `type_identifier`/`qualified_type`/etc., nodo distinto). `func f(a, b int)` -> 2,
        `func f(a int)` -> 1. Defensivo: si una declaración no tuviera ningún `identifier`,
        cuenta 1.
      - `variadic_parameter_declaration`: siempre 1 nombre (`func f(xs ...int)` -> 1); Go no
        permite agrupar varios nombres en un variadic.
    El receiver de un method_declaration NO llega aquí (campo `receiver`, no `parameters`):
    comportamiento inalterado.
    """
    count = 0
    for child in params_node.named_children:
        if child.type == "parameter_declaration":
            names = [c for c in child.named_children if c.type == "identifier"]
            count += len(names) if names else 1
        elif child.type == "variadic_parameter_declaration":
            count += 1
        else:
            count += 1  # defensivo: nodo declarado no reconocido
    return count

SPECS = [
    LangSpec("typescript", (".ts",), _ts_loader, _JSTS_FUNCS, _JSTS_DECISION, _JSTS_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_JSTS_ANON),
    LangSpec("tsx", (".tsx",), _tsx_loader, _JSTS_FUNCS, _JSTS_DECISION, _JSTS_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_JSTS_ANON),
    LangSpec("javascript", (".js", ".jsx", ".mjs", ".cjs"), _ts_loader, _JSTS_FUNCS,
             _JSTS_DECISION, _JSTS_NEST, "binary_expression", ("&&", "||"),
             anon_name_parents=_JSTS_ANON),
    LangSpec("rust", (".rs",), _rust_loader, _RUST_FUNCS, _RUST_DECISION, _RUST_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_RUST_ANON),
    LangSpec("go", (".go",), _go_loader, _GO_FUNCS, _GO_DECISION, _GO_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_GO_ANON,
             params_counter=_go_param_count),
]


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


class TreeSitterBackend(_mb.Backend):
    """Backend de métricas para un lenguaje, parametrizado por su LangSpec."""
    tool = "ccdd-treesitter-metrics"
    version = "1"

    def __init__(self, spec, ts_language, parser):
        self.spec = spec
        self.language = spec.language
        self.extensions = spec.extensions
        self._lang = ts_language
        self._parser = parser

    # --- métricas por función ---
    def _decision_weight(self, n, spec):
        """+1 si el nodo es una decisión o un operador booleano contado (guard clauses planas)."""
        if n.type in spec.decision_nodes:
            return 1
        if n.type == spec.boolop_node:
            op = n.child_by_field_name("operator")
            if op is not None and op.type in spec.boolop_ops:
                return 1
        return 0

    def _cyclomatic(self, fn):
        spec = self.spec
        return 1 + sum(self._decision_weight(n, spec) for n in _walk(fn))

    def _nesting(self, node, depth=0):
        best = depth
        for child in node.children:
            d = depth + 1 if child.type in self.spec.nest_nodes else depth
            best = max(best, self._nesting(child, d))
        return best

    def _params(self, fn):
        fp = fn.child_by_field_name(self.spec.params_field)
        if fp is None:
            return 0
        # Hook opcional por lenguaje (p. ej. Go agrupa nombres que comparten tipo en un solo
        # nodo declaración). Default: len de named_children del nodo parameters.
        if self.spec.params_counter is not None:
            return self.spec.params_counter(fp)
        return len(fp.named_children)

    def _name(self, fn):
        nm = fn.child_by_field_name(self.spec.name_field)
        if nm is not None:
            return nm.text.decode("utf-8", "replace")
        # Función anónima (arrow/closure/func literal): subir por los ancestros y, si uno
        # coincide con una regla de `anon_name_parents`, extraer el identificador del campo.
        # El campo puede ser el identificador directamente o un nodo-lista que lo envuelve
        # (p. ej. el `left` de un short_var_declaration de Go es una expression_list con `f`).
        ident_like = ("identifier", "field_identifier", "type_identifier")
        p = fn.parent
        for _ in range(3):
            if p is None:
                break
            field = self.spec.anon_name_parents.get(p.type)
            if field is not None:
                val = p.child_by_field_name(field)
                if val is not None:
                    if val.type in ident_like:
                        return val.text.decode("utf-8", "replace")
                    for c in val.named_children:
                        if c.type in ident_like:
                            return c.text.decode("utf-8", "replace")
            p = p.parent
        return "<anonymous>"

    def measure(self, src):
        tree = self._parser.parse(bytes(src, "utf-8"))
        out = []
        for n in _walk(tree.root_node):
            if n.type in self.spec.function_nodes:
                out.append({
                    "function": self._name(n), "line": n.start_point[0] + 1,
                    "cyclomatic": self._cyclomatic(n), "nesting_depth": self._nesting(n),
                    "parameter_count": self._params(n),
                    "function_length": n.end_point[0] - n.start_point[0] + 1,
                })
        return out


def register_all():
    """Registra un backend tree-sitter por cada gramática DISPONIBLE. Devuelve los lenguajes
    registrados. No lanza si tree_sitter o una gramática no están instalados (dep opcional)."""
    try:
        from tree_sitter import Language, Parser
    except ImportError:
        return []
    registered = []
    for spec in SPECS:
        try:
            lang = Language(spec.grammar_loader())
            parser = Parser(lang)
        except Exception:
            continue  # gramática no instalada / incompatible: se omite, no se rompe
        _mb.register(TreeSitterBackend(spec, lang, parser))
        registered.append(spec.language)
    return registered


REGISTERED = register_all()
