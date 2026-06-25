"""mutdef_check.py — núcleo del gate de defaults mutables. STUB: lo implementa el modelo pequeño
(glm) bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast

_MUTABLE_FACTORIES = {"list", "dict", "set"}


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


def _is_mutable_default(node):
    """True si el default es literal List/Dict/Set o Call a Name en {list,dict,set}."""
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in _MUTABLE_FACTORIES
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