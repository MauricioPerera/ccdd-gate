"""bareexcept_check.py — núcleo del gate de except desnudo. STUB: lo implementa el modelo pequeño
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


def _bare_handlers(fn_node):
    """Lineno de los ExceptHandler con type is None dentro del cuerpo de fn_node, ordenados."""
    lines = [h.lineno for h in ast.walk(fn_node)
             if isinstance(h, ast.ExceptHandler) and h.type is None]
    return sorted(lines)


def bare_except_lines(source: str, fn_name: str, target_line: int = None) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    fn_node = _find_function(tree, fn_name, target_line)
    if fn_node is None:
        return []
    return _bare_handlers(fn_node)