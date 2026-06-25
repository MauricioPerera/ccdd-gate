"""purity_check.py — núcleo del gate de pureza. STUB: lo implementa el modelo pequeño (glm) bajo el
CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


_DENYLIST = ("print", "open", "input", "eval", "exec", "__import__")


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


def _node_mark(node):
    """Marca de impureza de UN nodo, o None si no es impuro: Call al denylist, Global, Nonlocal,
    Import/ImportFrom. Solo stdlib (ast). Sin ejecutar el código."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _DENYLIST:
            return func.id
        return None
    if isinstance(node, ast.Global):
        return "global"
    if isinstance(node, ast.Nonlocal):
        return "nonlocal"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    return None


def _collect_marks(body):
    """Marcas de impureza del CUERPO (lista de sentencias): Calls al denylist, Global, Nonlocal,
    Import/ImportFrom. Solo stdlib (ast). Sin ejecutar el código."""
    marks = set()
    for stmt in body:
        for node in ast.walk(stmt):
            mark = _node_mark(node)
            if mark is not None:
                marks.add(mark)
    return marks


def impure_operations(source: str, fn_name: str, target_line: int = None) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    fn = _find_function(tree, fn_name, target_line)
    if fn is None:
        return []
    return sorted(_collect_marks(fn.body))