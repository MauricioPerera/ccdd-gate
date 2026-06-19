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
    """
    def __init__(self, language, extensions, grammar_loader, function_nodes, decision_nodes,
                 nest_nodes, boolop_node, boolop_ops, params_field="parameters", name_field="name"):
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


# --- gramáticas concretas ---------------------------------------------------------------------
def _ts_loader():
    import tree_sitter_typescript as tsts
    return tsts.language_typescript()


def _tsx_loader():
    import tree_sitter_typescript as tsts
    return tsts.language_tsx()


# Nodos comunes a TS/JS (la gramática typescript de tree-sitter cubre ambos sintácticamente).
_JSTS_FUNCS = ("function_declaration", "function_expression", "arrow_function",
               "method_definition", "generator_function", "generator_function_declaration")
_JSTS_DECISION = ("if_statement", "for_statement", "for_in_statement", "while_statement",
                  "do_statement", "ternary_expression", "catch_clause",
                  "switch_case", "switch_default")
# try_statement anida pero NO es decisión (espejo de Python: Try anida, ExceptHandler decide).
_JSTS_NEST = ("if_statement", "for_statement", "for_in_statement", "while_statement",
              "do_statement", "try_statement")

SPECS = [
    LangSpec("typescript", (".ts",), _ts_loader, _JSTS_FUNCS, _JSTS_DECISION, _JSTS_NEST,
             "binary_expression", ("&&", "||")),
    LangSpec("tsx", (".tsx",), _tsx_loader, _JSTS_FUNCS, _JSTS_DECISION, _JSTS_NEST,
             "binary_expression", ("&&", "||")),
    LangSpec("javascript", (".js", ".jsx", ".mjs", ".cjs"), _ts_loader, _JSTS_FUNCS,
             _JSTS_DECISION, _JSTS_NEST, "binary_expression", ("&&", "||")),
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
        return len(fp.named_children) if fp is not None else 0

    def _name(self, fn):
        nm = fn.child_by_field_name(self.spec.name_field)
        if nm is not None:
            return nm.text.decode("utf-8", "replace")
        p = fn.parent  # arrow/expresión anónima: tomar el nombre del declarador contenedor
        if p is not None and p.type in ("variable_declarator", "pair", "public_field_definition"):
            key = p.child_by_field_name("name") or p.child_by_field_name("key")
            if key is not None:
                return key.text.decode("utf-8", "replace")
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
