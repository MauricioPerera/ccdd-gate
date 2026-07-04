"""deps_check.py — enforcement de deps_allowed (anti-slopsquatting). Implementa unauthorized_imports
bajo el CCDD gate. Solo stdlib (ast, os, sys, pathlib); sin estado global, sin ejecutar el código analizado."""
import ast
import os
import sys
from pathlib import Path


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


def _local_module_names(local_roots):
    """Devuelve el conjunto de nombres de módulo top-level resolvibles LOCALMENTE bajo alguno de los
    `local_roots`. Un nombre `m` es local si existe `<root>/m.py` o `<root>/m/__init__.py` para algún
    root. Solo acepta identifiers válidos (un archivo `foo-bar.py` no es importable como módulo) e
    ignora `__init__`. No recursa: basta mirar el top-level de cada root porque _toplevel() reduce
    cualquier import punteado a su primer segmento. Errores de FS (dir inexistente, permisos) se
    ignoran: ese root simplemente no aporta nombres."""
    names = set()
    for root in local_roots or []:
        try:
            rp = Path(root)
        except Exception:
            continue
        if not rp.is_dir():
            continue
        try:
            entries = list(os.scandir(rp))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_file() and name.endswith(".py"):
                stem = name[:-3]
                if stem and stem != "__init__" and stem.isidentifier():
                    names.add(stem)
            elif entry.is_dir() and name.isidentifier() and (rp / name / "__init__.py").exists():
                names.add(name)
    return names


def unauthorized_imports(source: str, deps_allowed: list, local_roots=None) -> list:
    """Flaggea imports top-level del `source` que no estén en `deps_allowed` (ni en la stdlib).

    `local_roots` (opcional, retrocompatible): lista de directorios de búsqueda locales. Si se pasa
    (no-None), los imports top-level que resuelvan a un módulo/paquete local bajo alguno de esos roots
    (`<root>/m.py` o `<root>/m/__init__.py`) se eximen automáticamente. Si es None o se omite, el
    comportamiento es EXACTAMENTE el previo: todo import no-stdlib fuera de `deps_allowed` se flaggea
    (incluidos módulos locales del propio proyecto)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    allowed = set(deps_allowed) | sys.stdlib_module_names | {"__future__"}
    if local_roots is not None:
        allowed |= _local_module_names(local_roots)
    flagged = {m for m in _imported_modules(tree) if m not in allowed}
    return sorted(flagged)