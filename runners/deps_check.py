"""deps_check.py — enforcement de deps_allowed (anti-slopsquatting). Implementa unauthorized_imports
bajo el CCDD gate. Solo stdlib (ast, sys); sin I/O, sin estado global, sin ejecutar el código analizado."""
import ast
import sys


def _toplevel(name: str) -> str:
    """Devuelve el módulo top-level de un nombre punteado ('a.b.c' -> 'a')."""
    return name.split(".")[0]


def _imported_modules(tree):
    """Itera los módulos top-level importados por un AST, ignorando imports relativos (level>=1)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _toplevel(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 1 or not node.module:
                continue
            yield _toplevel(node.module)


def _import_module_aliases(tree):
    """Nombres bound a importlib.import_module vía `from importlib import import_module` (o alias).
    Permite tratar `import_module("x")` (Name suelto) como import dinámico de importlib."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib" and node.level == 0:
            for alias in node.names:
                if alias.name == "import_module":
                    aliases.add(alias.asname or alias.name)
    return aliases


def _literal_str(node):
    """El valor str si node es un string literal (ast.Constant); si no None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _dynamic_imports(tree):
    """Módulos top-level importados DINÁMICAMENTE: `__import__("x")`, `importlib.import_module("x")`
    y `import_module("x")` (cuando viene de `from importlib import import_module`).

    - Si el argumento es un string literal, ese módulo se trata como import de tercero y se somete a
      deps_allowed/stdlib igual que un import estático.
    - Si el argumento NO es literal, no podemos resolver el módulo estáticamente. Reportamos
      "importlib" como mecanismo no-autorizado. Como importlib es stdlib (siempre en `allowed`), el
      filtro final lo descarta salvo que el caller haya retirado importlib explícitamente. Así se evita
      marcar imports dinámicos legítimos de stdlib (falso positivo) pero queda el gancho para el caso
      teórico en que importlib no se permita."""
    aliases = _import_module_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        mod = None
        if isinstance(func, ast.Name) and func.id == "__import__":
            mod = _literal_str(node.args[0]) if node.args else None
        elif isinstance(func, ast.Attribute) and func.attr == "import_module" \
                and isinstance(func.value, ast.Name) and func.value.id == "importlib":
            mod = _literal_str(node.args[0]) if node.args else None
        elif isinstance(func, ast.Name) and func.id in aliases:
            mod = _literal_str(node.args[0]) if node.args else None
        else:
            continue
        if mod is not None:
            yield _toplevel(mod)
        else:
            # arg dinámico no resoluble -> señalamos el mecanismo (ver docstring).
            yield "importlib"


def unauthorized_imports(source: str, deps_allowed: list) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    allowed = set(deps_allowed) | sys.stdlib_module_names | {"__future__"}
    flagged = {m for m in _imported_modules(tree) if m not in allowed}
    # FALSO NEGATIVO: imports dinámicos (__import__/importlib.import_module) no los veía el recorrido
    # estático de Import/ImportFrom. Se someten a la misma regla de allowed.
    flagged |= {m for m in _dynamic_imports(tree) if m not in allowed}
    return sorted(flagged)