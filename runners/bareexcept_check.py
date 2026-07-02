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


def _walk_local(root):
    """Yield root y cada descendiente, SIN descender en FunctionDef/AsyncFunctionDef/Lambda anidados.
    Los antipatrones de una función/lambda anidados pertenecen a esa función interna, no al target
    exterior (falso positivo: atribuirlos al target)."""
    yield root
    for child in ast.iter_child_nodes(root):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from _walk_local(child)


def _is_bare(handler):
    """True si el ExceptHandler es desnudo: type is None (`except:`) o tupla vacía (`except ():`,
    que atrapa todo igual que un bare pero su type es ast.Tuple con elts==[])."""
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Tuple) and len(handler.type.elts) == 0:
        return True
    return False


def _bare_handlers(fn_node):
    """Lineno de los ExceptHandler desnudos (type None o tupla vacía) del cuerpo de fn_node, ordenados.
    NO desciende en funciones/lambdas anidados."""
    lines = [h.lineno for h in _walk_local(fn_node)
             if isinstance(h, ast.ExceptHandler) and _is_bare(h)]
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