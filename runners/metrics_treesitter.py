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
    params_node_types : fallback OPCIONAL para gramáticas que NO exponen la lista de parámetros
                        bajo ningún field (kotlin: function_value_parameters / lambda_parameters
                        son hijos directos sin campo): si params_field no resuelve, se toma el
                        primer hijo directo cuyo tipo esté en este set. Default None: cero
                        cambio para el resto de los backends.
    name_resolver    : hook OPCIONAL (nodo función) -> nodo identifier | None, consultado solo
                        si name_field no resuelve. Necesario cuando el nombre no cuelga de un
                        field plano (C: identifier anidado en el declarator; kotlin: ver la nota
                        de su spec). Default None: cero cambio para el resto.
    """
    def __init__(self, language, extensions, grammar_loader, function_nodes, decision_nodes,
                 nest_nodes, boolop_node, boolop_ops, params_field="parameters", name_field="name",
                 anon_name_parents=None, params_counter=None, params_node_types=None,
                 name_resolver=None):
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
        self.params_node_types = set(params_node_types) if params_node_types else None
        self.name_resolver = name_resolver


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


def _java_loader():
    import tree_sitter_java as tsjava
    return tsjava.language()


def _csharp_loader():
    import tree_sitter_c_sharp as tscs
    return tscs.language()


def _php_loader():
    import tree_sitter_php as tsphp
    # PHP puro (código fuente .php que arranca con `<?php`): `language_php_only()` expone un
    # AST limpio (program > function_definition/method_declaration/...). `language_php()` es
    # para PHP embebido en HTML (envuelve el source en `text/html` + `program_fragment`); sobre
    # fuente pura produce un árbol más ruidoso y menos estable. Para medir .php usamos php_only.
    return tsphp.language_php_only()


def _ruby_loader():
    import tree_sitter_ruby as tsrb
    return tsrb.language()


def _kotlin_loader():
    import tree_sitter_kotlin as tskt
    return tskt.language()


def _c_loader():
    import tree_sitter_c as tsc
    return tsc.language()


def _swift_loader():
    import tree_sitter_swift as tss
    return tss.language()


def _cpp_loader():
    import tree_sitter_cpp as tscpp
    return tscpp.language()


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

# --- Java ----------------------------------------------------------------------
# method_declaration (métodos) y constructor_declaration (constructores) son las unidades
# con cuerpo; lambda_expression es la función anónima (análogo a arrow_function de TS).
# Decisiones: if/for/enhanced_for_statement (el `foreach` de Java)/while/do + ternary_expression
# + catch_clause. switch_label cubre `case X:` Y `default:` (la gramática NO los distingue por
# tipo): se cuenta cada switch_label +1 (modelo TS: default suma, ver reporte). try_statement
# anida SIN ser decisión — espejo de Python/TS (Try anida, ExceptHandler/catch decide).
_JAVA_FUNCS = ("method_declaration", "constructor_declaration", "lambda_expression")
_JAVA_DECISION = ("if_statement", "for_statement", "enhanced_for_statement", "while_statement",
                  "do_statement", "ternary_expression", "catch_clause", "switch_label")
_JAVA_NEST = ("if_statement", "for_statement", "enhanced_for_statement", "while_statement",
              "do_statement", "try_statement")
# Lambda anónima: `Runnable r = () -> …;` → cuelga de un variable_declarator (campo "name").
_JAVA_ANON = {"variable_declarator": "name"}

# --- C# ------------------------------------------------------------------------
# method_declaration, constructor_declaration y local_function_statement (funciones locales
# anidadas) son las unidades con cuerpo; lambda_expression es la anónima.
# Decisiones: if/for/foreach/while/do + conditional_expression (ternario `?:`) + catch_clause.
# switch_section es la unidad de rama de switch (engloba el/los `case`/`default` y su cuerpo;
# la gramática NO expone el label como nodo propio): se cuenta cada switch_section +1 (modelo
# TS: default suma, ver reporte). try_statement/lock_statement/using_statement anidan SIN ser
# decisión: análogos de `with`/unsafe_block (bloques de ámbito sin bifurcación).
# using_DIRECTIVE (`using System;`, import) NO está: no tiene bloque ni anida.
_CSHARP_FUNCS = ("method_declaration", "constructor_declaration", "local_function_statement",
                 "lambda_expression")
_CSHARP_DECISION = ("if_statement", "for_statement", "foreach_statement", "while_statement",
                    "do_statement", "conditional_expression", "catch_clause", "switch_section")
_CSHARP_NEST = ("if_statement", "for_statement", "foreach_statement", "while_statement",
                "do_statement", "try_statement", "lock_statement", "using_statement")
# Lambda anónima: `Func<int,int> lam = x => x + 1;` → variable_declarator (campo "name").
_CSHARP_ANON = {"variable_declarator": "name"}

# --- PHP (php_only) ------------------------------------------------------------
# function_definition (función libre) y method_declaration (métodos, incluido __construct) son
# las unidades con cuerpo; arrow_function (`fn()=>…`) y anonymous_function (`function(){…}` con
# `use`) son las anónimas (closures).
# Decisiones: if/for/foreach/while/do + conditional_expression (ternario `?:`) + catch_clause.
# switch: case_statement es cada `case X:` explícito; default_statement es la rama por defecto y
# NO suma (modelo "ramas − 1", análogo a Go/Python/Rust): la gramática SÍ distingue case/default
# por tipo, a diferencia de Java/C#. try_statement anida SIN ser decisión (catch_clause decide).
# PHP carece de with/unsafe/lock: try/finally es el análogo de nido-sin-decisión (ver deep_nesting).
_PHP_FUNCS = ("function_definition", "method_declaration", "arrow_function", "anonymous_function")
_PHP_DECISION = ("if_statement", "for_statement", "foreach_statement", "while_statement",
                 "do_statement", "conditional_expression", "catch_clause", "case_statement")
_PHP_NEST = ("if_statement", "for_statement", "foreach_statement", "while_statement",
             "do_statement", "try_statement")
# Cierre anónimo: `$f = fn()=>…;` / `$g = function(){…}` → assignment_expression (campo "left"
# → variable_name → nodo `name`). Requiere reconocer el nodo `name` (ver ident_like en _name).
_PHP_ANON = {"assignment_expression": "left"}

# --- Ruby ----------------------------------------------------------------------
# method (`def`) y singleton_method (`def self.x`) son las unidades con cuerpo; lambda es el
# literal `->(a){…}`, la única anónima con nodo propio (`lambda {}` / `proc {}` son calls con
# block, indistinguibles de cualquier call con bloque sin resolución semántica: NO se cuentan).
# OJO: esta gramática nombra sus reglas con la keyword desnuda (`if`, `while`, `when`, `begin`)
# igual que sus tokens anónimos: el conteo filtra por is_named (ver _decision_weight/_nesting).
# Decisiones: if/elsif/unless/while/until/for + sus formas modificador (`return 1 if x`), cada
# `when` de un case (`else` es nodo propio y NO suma: camino base, modelo "ramas − 1" análogo a
# Go/PHP/Python/Rust), rescue (el catch de Ruby, incluido rescue_modifier) y conditional (el
# ternario `x ? a : b`). begin anida SIN ser decisión: begin/ensure es el try/finally de Ruby,
# análogo del `with` de Python (rescue decide, begin anida). Los bloques de método (`do…end` /
# `{ }` de un call) NO anidan ni son funciones: son argumentos (contarlos inflaría nesting
# frente al baseline Python en cada `.each`).
_RUBY_FUNCS = ("method", "singleton_method", "lambda")
_RUBY_DECISION = ("if", "elsif", "unless", "while", "until", "for", "when", "conditional",
                  "rescue", "if_modifier", "unless_modifier", "while_modifier",
                  "until_modifier", "rescue_modifier")
_RUBY_NEST = ("if", "elsif", "unless", "while", "until", "for", "begin")
# Lambda anónima: `f = ->(x){…}` → cuelga de un assignment (campo "left" → identifier).
_RUBY_ANON = {"assignment": "left"}

# --- Kotlin --------------------------------------------------------------------
# function_declaration (`fun`), lambda_literal (`{ x -> … }`) y anonymous_function
# (`fun(x) = …`) son las unidades medidas. La gramática kotlin expone POCOS fields: la lista de
# parámetros no cuelga de ningún campo (params_node_types la localiza por TIPO) y el nombre se
# extrae con name_resolver. name_field se deja deliberadamente sin resolver
# ("__via_name_resolver__"): así sig_treesitter — que solo entiende fields planos y, sin field
# de parámetros, reportaría SIEMPRE aridad 0 en silencio — declara kotlin no-soportado y
# tc_lint conserva su fallback genérico anunciado (aridad real + warning), exactamente el
# comportamiento previo a esta tarea (congelado en test_sig_treesitter).
# Decisiones: if/for/while/do_while + cada when_entry (INCLUIDO el `else ->`: la gramática no lo
# distingue por tipo — modelo TS/Java, ver reporte TAREA-RKC) + catch_block.
# try_expression anida SIN ser decisión: try/finally es el análogo del `with` de Python.
_KOTLIN_FUNCS = ("function_declaration", "lambda_literal", "anonymous_function")
_KOTLIN_DECISION = ("if_expression", "for_statement", "while_statement", "do_while_statement",
                    "when_entry", "catch_block")
_KOTLIN_NEST = ("if_expression", "for_statement", "while_statement", "do_while_statement",
                "try_expression")
# Lambda anónima: `val f = { x -> … }` → property_declaration SIN fields: el valor de la regla
# se interpreta como TIPO de hijo (variable_declaration → identifier), ver _anon_ident.
_KOTLIN_ANON = {"property_declaration": "variable_declaration"}

# --- C -------------------------------------------------------------------------
# function_definition es la única unidad con cuerpo (C no tiene anónimas: sin anon_name_parents).
# Nombre y parámetros viven bajo el campo "declarator" ANIDADO (function_definition >
# [pointer_declarator >] function_declarator > identifier / parameter_list): name_resolver y
# params_counter descienden por ese campo. name_field="name" no existe en esta gramática y es
# deliberado: sig_treesitter (fields planos) declara C no-soportado y tc_lint usa su fallback
# genérico anunciado, en vez de extraer un nombre basura tipo "f(int a)" del declarator.
# Decisiones: if/for/while/do + conditional_expression (ternario `?:`) + case_statement. La
# gramática NO distingue `case X:` de `default:` por tipo (ambos case_statement): default suma,
# modelo TS/Java (ver reporte TAREA-RKC). switch_statement NO está en nest (espejo de TS).
# labeled_statement anida SIN ser decisión: el bloque etiquetado `out: { … }` (idioma del goto
# de limpieza) es el análogo local del `with` de Python / unsafe de Rust — C no tiene
# try/with/lock, y un `{}` suelto (compound_statement) doble-contaría cada cuerpo de if/for.
_C_FUNCS = ("function_definition",)
_C_DECISION = ("if_statement", "for_statement", "while_statement", "do_statement",
               "conditional_expression", "case_statement")
_C_NEST = ("if_statement", "for_statement", "while_statement", "do_statement",
           "labeled_statement")

# --- Swift -------------------------------------------------------------------------
# function_declaration es la única unidad con cuerpo. Closures (lambda_literal) se asignan
# a variables via property_declaration (p. ej. `let f = { x in x }`).
# Decisiones: if_statement/for_statement/while_statement/guard_statement +
# switch_entry (cada case o default) + conditional_expression (ternario `x ? a : b`).
# do_statement anida SIN ser decisión: equivalente del `try` de Python (do-catch maneja
# errores, do anida, catch decide — pero la gramática no los distingue por nodo).
# Boolops: binary_expression con `&&`/`||`.
# Parámetros: la lista de parámetros no cuelga de un field — son hijos directos
# `parameter` del function_declaration (hook params_node_types lo localiza por tipo).
# Nombre: no cuelga de un field `name` — es un nodo `simple_identifier` hijo directo.
_SWIFT_FUNCS = ("function_declaration", "lambda_literal")
_SWIFT_DECISION = ("if_statement", "for_statement", "while_statement",
                   "guard_statement", "switch_entry", "conditional_expression")
_SWIFT_NEST = ("if_statement", "for_statement", "while_statement", "do_statement",
              "guard_statement")
# Lambda asignada: `let f = { x in … }` → property_declaration (campo "pattern" → simple_identifier)
_SWIFT_ANON = {"property_declaration": "pattern"}

# --- C++ -----------------------------------------------------------------------
# function_definition es la única unidad con cuerpo. Lambdas (lambda_expression) aparecen
# en contextos de asignación (init_declarator con campo "name" → identifier).
# Decisiones: if_statement/for_statement/while_statement/do_statement + conditional_expression
# (ternario) + case_statement (cada case o default, ambos son case_statement).
# Boolops: binary_expression con `&&`/`||`.
# Parámetros: cuelgan bajo function_declarator > parameter_list (usar params_field="function_declarator",
# params_counter descendiente).
# Nombre: dentro de function_declarator (puede ser qualified_identifier para métodos fuera de clase):
# usar name_resolver que maneja ambos casos.
# Nido-sin-decisión: bloque etiquetado (labeled_statement, idioma del goto de limpieza, análogo a C).
_CPP_FUNCS = ("function_definition", "lambda_expression")
_CPP_DECISION = ("if_statement", "for_statement", "while_statement", "do_statement",
                 "conditional_expression", "case_statement")
_CPP_NEST = ("if_statement", "for_statement", "while_statement", "do_statement",
            "labeled_statement")
# Lambda asignada: `auto lam = [](int x) { … };` → init_declarator (campo "name" → identifier)
_CPP_ANON = {"init_declarator": "name"}


def _swift_params_by_type(fn_node):
    """Cuenta parámetros Swift (son hijos `parameter` directos, no bajo un field).

    Los parámetros en function_declaration son nodos hijo de tipo `parameter`, no bajo
    un contenedor de parámetros (a diferencia de otros lenguajes). Se cuenta directamente.
    """
    return sum(1 for c in fn_node.named_children if c.type == "parameter")


def _cpp_params_count(func_declarator):
    """Cuenta parámetros C++ dentro del function_declarator o function_definition."""
    params_list = _cpp_find_params_list(func_declarator)
    if params_list is None:
        return 0
    count = sum(1 for child in params_list.named_children
                if child.type in ("parameter_declaration", "variadic_parameter"))
    return count if count > 0 else sum(1 for _ in params_list.named_children)


def _cpp_find_params_list(node):
    """Localiza el nodo parameter_list en un function_declarator o function_definition."""
    if node.type == "function_declarator":
        return _cpp_get_params_from_declarator(node)
    if node.type == "function_definition":
        declarator = node.child_by_field_name("declarator")
        while declarator and declarator.type != "function_declarator":
            declarator = declarator.child_by_field_name("declarator")
        return _cpp_get_params_from_declarator(declarator) if declarator else None
    return None


def _cpp_get_params_from_declarator(declarator):
    """Extrae parameter_list de un function_declarator."""
    params = declarator.child_by_field_name("parameters")
    if params is not None:
        return params
    for child in declarator.named_children:
        if child.type == "parameter_list":
            return child
    return None


def _cpp_name_node(fn):
    """Nodo identifier del nombre de una función C++.

    function_definition > function_declarator > (identifier | qualified_identifier).
    Si es qualified_identifier (método fuera de clase: T C::method), el nombre es
    el identifier hijo derecho (después del ::).
    """
    declarator = fn.child_by_field_name("declarator")
    if declarator is None:
        return None
    # Buscar identifier o qualified_identifier en el declarator
    for child in declarator.named_children:
        if child.type == "identifier":
            return child
        if child.type == "qualified_identifier":
            # El último hijo es el identifier (después del ::)
            idents = [c for c in child.named_children if c.type == "identifier"]
            return idents[-1] if idents else None
        # Descender recursivamente (puede haber abstract_function_declarator)
        if child.type in ("abstract_function_declarator", "pointer_declarator",
                         "reference_declarator", "array_declarator"):
            node = _cpp_name_node_recurse(child)
            if node:
                return node
    return None


def _cpp_name_node_recurse(node):
    """Helper recursivo para descender en declarators anidados."""
    for child in node.named_children:
        if child.type == "identifier":
            return child
        if child.type == "qualified_identifier":
            idents = [c for c in child.named_children if c.type == "identifier"]
            return idents[-1] if idents else None
        if child.type in ("abstract_function_declarator", "pointer_declarator",
                         "reference_declarator", "array_declarator"):
            node = _cpp_name_node_recurse(child)
            if node:
                return node
    return None


def _swift_name_node(fn):
    """Nodo identifier del nombre de una función Swift.

    function_declaration tiene el nombre como nodo hijo directo simple_identifier.
    """
    for child in fn.named_children:
        if child.type == "simple_identifier":
            return child
    return None


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

def _c_param_count(decl_node):
    """Cuenta parámetros C descendiendo al `function_declarator` anidado.

    En C, params_field="declarator" entrega el declarador del function_definition (que puede
    envolverse en pointer_declarator: `int *f(…)`); se desciende por el campo "declarator"
    hasta el function_declarator y se cuenta su parameter_list:
      - `parameter_declaration` CON declarator: 1 nombre (`int a` -> 1).
      - `parameter_declaration` SIN declarator: 0 — es el caso `int f(void)` (0 parámetros).
      - `variadic_parameter` (`...`): 1 slot extra, espejo del variadic de Go.
    """
    node = decl_node
    while node is not None and node.type != "function_declarator":
        node = node.child_by_field_name("declarator")
    params = node.child_by_field_name("parameters") if node is not None else None
    if params is None:
        return 0
    count = 0
    for child in params.named_children:
        if child.type == "parameter_declaration":
            count += 1 if child.child_by_field_name("declarator") is not None else 0
        else:
            count += 1  # variadic_parameter u otro nodo declarado
    return count


def _c_name_node(fn):
    """Nodo identifier del nombre de una función C: desciende por el campo "declarator"
    (function_definition > [pointer_declarator >] function_declarator > identifier)."""
    node = fn.child_by_field_name("declarator")
    while node is not None and node.type != "identifier":
        node = node.child_by_field_name("declarator")
    return node


def _kotlin_name_node(fn):
    """Nombre de una función kotlin: el field "name" REAL de la gramática. Se consulta vía
    name_resolver (y no vía name_field) para que sig_treesitter no vea a kotlin como
    soportado — ver la nota del bloque Kotlin."""
    return fn.child_by_field_name("name")


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
    LangSpec("java", (".java",), _java_loader, _JAVA_FUNCS, _JAVA_DECISION, _JAVA_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_JAVA_ANON),
    LangSpec("csharp", (".cs",), _csharp_loader, _CSHARP_FUNCS, _CSHARP_DECISION, _CSHARP_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_CSHARP_ANON),
    LangSpec("php", (".php",), _php_loader, _PHP_FUNCS, _PHP_DECISION, _PHP_NEST,
             "binary_expression", ("&&", "||"), anon_name_parents=_PHP_ANON),
    LangSpec("ruby", (".rb",), _ruby_loader, _RUBY_FUNCS, _RUBY_DECISION, _RUBY_NEST,
             "binary", ("&&", "||", "and", "or"), anon_name_parents=_RUBY_ANON),
    LangSpec("kotlin", (".kt", ".kts"), _kotlin_loader, _KOTLIN_FUNCS, _KOTLIN_DECISION,
             _KOTLIN_NEST, "binary_expression", ("&&", "||"),
             params_field="function_value_parameters",
             params_node_types=("function_value_parameters", "lambda_parameters"),
             name_field="__via_name_resolver__", name_resolver=_kotlin_name_node,
             anon_name_parents=_KOTLIN_ANON),
    LangSpec("c", (".c", ".h"), _c_loader, _C_FUNCS, _C_DECISION, _C_NEST,
             "binary_expression", ("&&", "||"), params_field="declarator",
             params_counter=_c_param_count, name_resolver=_c_name_node),
    LangSpec("swift", (".swift",), _swift_loader, _SWIFT_FUNCS, _SWIFT_DECISION, _SWIFT_NEST,
             "conjunction_expression", ("&&", "||"), params_field="parameters",
             anon_name_parents=_SWIFT_ANON, params_counter=_swift_params_by_type,
             name_resolver=_swift_name_node),
    LangSpec("cpp", (".cpp", ".cc", ".cxx", ".hpp"), _cpp_loader, _CPP_FUNCS,
             _CPP_DECISION, _CPP_NEST, "binary_expression", ("&&", "||"),
             params_field="function_declarator", params_counter=_cpp_params_count,
             name_resolver=_cpp_name_node, anon_name_parents=_CPP_ANON),
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
        """+1 si el nodo es una decisión o un operador booleano contado (guard clauses planas).

        Solo nodos NAMED: la gramática ruby nombra reglas con la keyword desnuda (`if`, `when`)
        y sus tokens anónimos comparten ese type — sin el filtro cada decisión contaría doble.
        Los demás lenguajes usan nombres con sufijo (if_statement…): cero cambio."""
        if n.type in spec.decision_nodes and n.is_named:
            return 1
        if n.type == spec.boolop_node:
            # Intentar localizar operador via field (mayoría de lenguajes)
            op = n.child_by_field_name("operator")
            if op is not None and op.type in spec.boolop_ops:
                return 1
            # Swift (conjunction_expression) usa nodos hijo de tipo "&&" o "||" (anónimos)
            if spec.boolop_node == "conjunction_expression":
                for child in n.children:  # Incluir children anónimos
                    if child.type in spec.boolop_ops:
                        return 1
        return 0

    def _cyclomatic(self, fn):
        spec = self.spec
        return 1 + sum(self._decision_weight(n, spec) for n in _walk(fn))

    def _nesting(self, node, depth=0):
        best = depth
        for child in node.children:
            # is_named: mismo filtro que _decision_weight (nodos ruby homónimos de sus tokens).
            d = depth + 1 if (child.type in self.spec.nest_nodes and child.is_named) else depth
            best = max(best, self._nesting(child, d))
        return best

    def _params(self, fn):
        fp = fn.child_by_field_name(self.spec.params_field)
        if fp is None and self.spec.params_node_types:
            # Gramáticas sin field para la lista de parámetros (kotlin): localizarla por TIPO
            # entre los hijos directos. Default None: cero cambio para el resto.
            fp = next((c for c in fn.named_children
                       if c.type in self.spec.params_node_types), None)
        if fp is None:
            # Si hay un hook params_counter, intentar llamarlo directamente con el nodo función
            # (necesario para lenguajes como Swift donde los parámetros son hijos del function_node
            # sin un field contenedor).
            if self.spec.params_counter is not None:
                return self.spec.params_counter(fn)
            return 0
        # Hook opcional por lenguaje (p. ej. Go agrupa nombres que comparten tipo en un solo
        # nodo declaración). Default: len de named_children del nodo parameters.
        if self.spec.params_counter is not None:
            return self.spec.params_counter(fp)
        return len(fp.named_children)

    def _anon_ident(self, p, ident_like):
        # Dado un ancestro `p` de una función anónima, si coincide con una regla de
        # `anon_name_parents`, extrae y devuelve el identificador del campo (o None).
        # El campo puede ser el identificador directamente o un nodo-lista que lo envuelve
        # (p. ej. el `left` de un short_var_declaration de Go es una expression_list con `f`).
        # PHP: el identificador de una variable es un nodo `name` dentro de `variable_name`
        # (p. ej. el `left` de un assignment_expression); los demás lenguajes usan `identifier`.
        field = self.spec.anon_name_parents.get(p.type)
        if field is None:
            return None
        val = p.child_by_field_name(field)
        if val is None:
            # Gramáticas sin fields en el ancestro (kotlin property_declaration): la regla se
            # interpreta como TIPO de hijo directo del que extraer el identificador.
            val = next((c for c in p.named_children if c.type == field), None)
        if val is None:
            return None
        if val.type in ident_like:
            return val.text.decode("utf-8", "replace")
        for c in val.named_children:
            if c.type in ident_like:
                return c.text.decode("utf-8", "replace")
        return None

    def _name(self, fn):
        nm = fn.child_by_field_name(self.spec.name_field)
        if nm is None and self.spec.name_resolver is not None:
            # Hook por-gramática: C (identifier anidado en declarator), Swift (simple_identifier),
            # y kotlin (ver su spec).
            nm = self.spec.name_resolver(fn)
        if nm is not None:
            return nm.text.decode("utf-8", "replace")
        # Función anónima (arrow/closure/func literal): subir por los ancestros (hasta 3)
        # y, si uno coincide con una regla de `anon_name_parents`, extraer el identificador.
        ident_like = ("identifier", "field_identifier", "type_identifier", "name", "simple_identifier")
        p = fn.parent
        for _ in range(3):
            if p is None:
                break
            txt = self._anon_ident(p, ident_like)
            if txt is not None:
                return txt
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
