"""purity_check.py — núcleo del gate de pureza. STUB: lo implementa el modelo pequeño (glm) bajo el
CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


_DENYLIST = ("print", "open", "input", "eval", "exec", "__import__")

# attrs cuyo call por atributo es I/O sin importar el receptor (system/popen/write_text/urlopen/...):
# son lo bastante específicos como para que cualquier .system()/.write_text() sea I/O casi seguro.
_DANGEROUS_ATTRS = {
    "system", "popen", "Popen", "check_output",
    "write_text", "write_bytes", "read_text", "urlopen",
}
# módulos cuyo CUALQUIER método llamado se considera I/O (shutil.*, socket.*).
_IO_MODULES = {"shutil", "socket"}
# (módulo raíz) -> attrs concretos que cuentan como I/O. Restringe los attrs comunes (run/call/write/
# get/post) a su módulo para evitar falsos positivos: p.ej. dict.get NO se marca, requests.get sí.
_MODULE_ATTRS = {
    "os": {"system", "popen"},
    "subprocess": {"run", "call", "Popen", "check_output"},
    "sys": {"write"},  # sys.stdout.write / sys.stderr.write
    "requests": {"get", "post", "put", "patch", "delete", "request"},
}


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


def _root_name(node):
    """Nombre del receptor raíz de una cadena de atributos (a.b.c -> 'a'); None si no termina en Name."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _attr_call_mark(call):
    """Marca de impureza para un Call por atributo (os.system, subprocess.run, sys.stdout.write,
    requests.get, shutil.*, *.write_text, ...), o None si es seguro. Criterio:
    - attr en _DANGEROUS_ATTRS -> I/O casi seguro (marca = attr).
    - receptor raíz en _IO_MODULES -> cualquier método es I/O (marca = attr).
    - receptor raíz en _MODULE_ATTRS y attr en su set -> I/O (marca = attr).
    Así .get de un dict (receptor no 'requests') NO se marca; subprocess.run / requests.get sí."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr
    if attr in _DANGEROUS_ATTRS:
        return attr
    root = _root_name(func)
    if root in _IO_MODULES:
        return attr
    if root in _MODULE_ATTRS and attr in _MODULE_ATTRS[root]:
        return attr
    return None


def _node_mark(node):
    """Marca de impureza de UN nodo, o None si no es impuro: Call al denylist o por atributo peligroso,
    Global, Nonlocal, Import/ImportFrom. Solo stdlib (ast). Sin ejecutar el código."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _DENYLIST:
            return func.id
        return _attr_call_mark(node)
    if isinstance(node, ast.Global):
        return "global"
    if isinstance(node, ast.Nonlocal):
        return "nonlocal"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    return None


def _collect_marks(body):
    """Marcas de impureza del CUERPO (lista de sentencias): Calls al denylist o por atributo peligroso,
    Global, Nonlocal, Import/ImportFrom. Solo stdlib (ast). Sin ejecutar el código. NO desciende en
    funciones/lambdas anidados (sus marcas pertenecen a la función interna)."""
    marks = set()
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue  # def/lambda anidado: su cuerpo pertenece a la función interna, no al target
        for node in _walk_local(stmt):
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