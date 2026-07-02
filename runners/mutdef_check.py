"""mutdef_check.py — núcleo del gate de defaults mutables. STUB: lo implementa el modelo pequeño
(glm) bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


# fábricas mutables invocables como Name: list/dict/set/bytearray() y, vía `from collections import
# X`, también defaultdict/deque/OrderedDict().
_MUTABLE_FACTORIES = {"list", "dict", "set", "bytearray"}
_COLLECTION_FACTORIES = {"defaultdict", "deque", "OrderedDict"}
# dict.fromkeys(...) construye un dict mutable.
_DICT_FACTORY_ATTRS = {"fromkeys"}


def _find_function(tree, fn_name, target_line=None):
    """Devuelve la def de `fn_name`: si target_line se da, la de node.lineno == target_line;
    si no, la primera encontrada en orden de fuente. None si no hay match."""
    first = None
    for node in ast.walk(tree):
        if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name):
            continue
        if target_line is not None:
            if node.lineno == target_line:
                return node
            continue
        if first is None:
            first = node
    return first


def _is_mutable_receiver(node):
    """True si node es un receptor mutable: literal List/Dict/Set o un Call a fábrica mutable
    (list()/dict()/set()/bytearray()/collections.*/dict.fromkeys()/...)."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call):
        return _is_mutable_call(node)
    return False


def _is_mutable_call(call):
    """True si call construye un objeto mutable: list/dict/set/bytearray(), collections.defaultdict/
    deque/OrderedDict() (vía atributo o Name importado), dict.fromkeys(...), o <receptor mutable>.copy().
    frozenset()/tuple() NO son mutables (no se marcan)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in _MUTABLE_FACTORIES or func.id in _COLLECTION_FACTORIES
    if isinstance(func, ast.Attribute):
        attr = func.attr
        # collections.defaultdict/deque/OrderedDict()
        if attr in _COLLECTION_FACTORIES and isinstance(func.value, ast.Name) and func.value.id == "collections":
            return True
        # dict.fromkeys(...)
        if attr in _DICT_FACTORY_ATTRS and isinstance(func.value, ast.Name) and func.value.id == "dict":
            return True
        # <mutable>.copy()  (p.ej. [].copy(), {}.copy(), list().copy(), dict.fromkeys(k).copy())
        if attr == "copy" and _is_mutable_receiver(func.value):
            return True
        return False
    return False


def _is_mutable_default(node):
    """True si el default es literal List/Dict/Set o un Call que construye un mutable."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call):
        return _is_mutable_call(node)
    return False


def _positional_mutable_names(args):
    """Nombres de params posicionales (posonly + pos) con default mutable; args.defaults alinea
    con los ÚLTIMOS len(defaults) de posonlyargs+args.args."""
    params = list(args.posonlyargs) + list(args.args)
    defaults = args.defaults
    start = len(params) - len(defaults)
    names = []
    for i, default in enumerate(defaults):
        if _is_mutable_default(default):
            names.append(params[start + i].arg)
    return names


def _kwonly_mutable_names(args):
    """Nombres de params keyword-only con default mutable; kw_defaults trae None donde no hay."""
    names = []
    for param, default in zip(args.kwonlyargs, args.kw_defaults):
        if default is not None and _is_mutable_default(default):
            names.append(param.arg)
    return names


def mutable_defaults(source: str, fn_name: str, target_line: int = None) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    fn = _find_function(tree, fn_name, target_line)
    if fn is None:
        return []
    names = _positional_mutable_names(fn.args) + _kwonly_mutable_names(fn.args)
    return sorted(set(names))