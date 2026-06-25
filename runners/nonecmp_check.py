"""nonecmp_check.py — núcleo del gate de comparación con None por ==/!=. STUB: lo implementa el
modelo pequeño (glm) bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
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


def _has_none_operand(operands):
    """True si algún operando es ast.Constant con valor None."""
    return any(isinstance(o, ast.Constant) and o.value is None for o in operands)


def _is_eq_none_cmp(node):
    """True si node es ast.Compare con algún op Eq/NotEq y algún operando None."""
    return (
        isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        and _has_none_operand([node.left] + list(node.comparators))
    )


def none_eq_lines(source: str, fn_name: str, target_line: int = None) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    fn = _find_function(tree, fn_name, target_line)
    if fn is None:
        return []
    lines = [n.lineno for n in ast.walk(fn) if _is_eq_none_cmp(n)]
    return sorted(set(lines))