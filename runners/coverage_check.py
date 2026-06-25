"""coverage_check.py — núcleo del gate de cobertura. STUB: lo implementa el modelo pequeño (glm)
bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


def function_lines(source: str, fn_name: str, target_line: int = None) -> set:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    
    target_function = _find_function(tree, fn_name, target_line)
    if target_function is None:
        return set()
    
    lines = set()
    for node in ast.walk(target_function):
        if hasattr(node, 'lineno') and _is_statement(node):
            lines.add(node.lineno)
    
    # Remove the function definition line
    lines.discard(target_function.lineno)
    
    return lines


def _find_function(tree: ast.AST, fn_name: str, target_line: int = None) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == fn_name:
                if target_line is None or node.lineno == target_line:
                    return node
    return None


def _is_statement(node: ast.AST) -> bool:
    # Check if node is a statement (but not a function or class definition)
    return isinstance(node, (
        ast.Assign, ast.AugAssign, ast.AnnAssign,
        ast.Return, ast.Raise, ast.Assert,
        ast.Delete, ast.Import, ast.ImportFrom,
        ast.Global, ast.Nonlocal,
        ast.Expr,  # This includes function calls
        ast.Pass, ast.Break, ast.Continue,
        ast.If, ast.While, ast.For, ast.AsyncFor,
        ast.With, ast.AsyncWith,
        ast.Try, ast.TryStar,
        ast.Match,
    ))