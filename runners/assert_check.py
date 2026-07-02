"""assert_check.py — núcleo del gate de asserts en producción. STUB: lo implementa el modelo pequeño
(glm) bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


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


def _walk_local(root):
    """Yield root y cada descendiente, SIN descender en FunctionDef/AsyncFunctionDef/Lambda anidados.
    Los antipatrones de una función/lambda anidados pertenecen a esa función interna, no al target
    exterior (falso positivo: atribuirlos al target). No rompe metrics.py (ese mide anidadas a propósito
    y es otro archivo)."""
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from _walk_local(child)


def _assert_lines(fn_node):
    """Lineno de los ast.Assert del cuerpo de fn_node (incluye bloques anidados if/for/...), ordenados.
    NO desciende en funciones/lambdas anidados."""
    lines = [n.lineno for n in _walk_local(fn_node) if isinstance(n, ast.Assert)]
    return sorted(lines)


def assert_lines(source: str, fn_name: str, target_line: int = None) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    fn_node = _find_function(tree, fn_name, target_line)
    if fn_node is None:
        return []
    return _assert_lines(fn_node)