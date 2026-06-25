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


def unauthorized_imports(source: str, deps_allowed: list) -> list:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    allowed = set(deps_allowed) | sys.stdlib_module_names | {"__future__"}
    flagged = {m for m in _imported_modules(tree) if m not in allowed}
    return sorted(flagged)