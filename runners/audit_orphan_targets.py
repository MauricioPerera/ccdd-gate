#!/usr/bin/env python3
"""audit_orphan_targets.py — destaca CÓDIGO FUERA DEL FLUJO DE CONTRATO. Determinista, sin LLM.

Lista los `.py` de implementación (excluye tests, `__init__.py`, `conftest.py`) que NO son el
`target` de ningún task-contract. Es código que entró sin contrato ni gate: el orquestador
escribiendo implementación directa (lo que la política prohíbe), glue sin verificar, o cruft
(paquetes mal ubicados). La versión determinista del "¿se implementó fuera del gate?".

Pensado para CI de proyectos construidos ENTERAMENTE con CCDD (donde todo .py de producción debería
ser el target de un contrato). NO se cablea al ci_gate de ccdd-gate mismo: ccdd-gate no se construye
sobre sí mismo, así que sus runners no son targets. exit 1 si hay huérfanos.

Dirs exentas: por defecto `.git`, `.pytest_cache`, `__pycache__`, `node_modules`, `tests`. En un
repo mixto (fixtures/examples/benchmarks/scripts/integrations son soporte, no código sin contrato)
amplía el conjunto con `--skip-dir DIR` (repetible) o la variable `CCDD_ORPHAN_SKIP_DIR` (lista
separada por comas). El default no cambia salvo que se pida explícito.

Uso:  python audit_orphan_targets.py [raíz] [--skip-dir DIR ...]"""
import ast
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_composition import _contracts, _rel  # noqa: E402

_DEFAULT_SKIP = {".git", ".pytest_cache", "__pycache__", "node_modules", "tests"}
_SKIP_ENV = "CCDD_ORPHAN_SKIP_DIR"


def _skip_dirs(extra):
    """Conjunto de dirs exentas: default + extras (CLI `--skip-dir` / env `CCDD_ORPHAN_SKIP_DIR`).
    El default se mantiene si no hay extras ni env."""
    skip = set(_DEFAULT_SKIP)
    skip.update(extra)
    env = os.environ.get(_SKIP_ENV)
    if env:
        skip.update(p.strip() for p in env.split(",") if p.strip())
    return skip


def _is_excluded(rel, skip):
    """True si el .py (ruta RELATIVA a la raíz) NO es código de implementación (test/glue/cache).
    Se evalúa sobre la ruta relativa: si la raíz del proyecto está bajo un dir exento, NO debe
    excluir todo. `skip` es el conjunto de dirs exentas (default + extras)."""
    if any(part in skip for part in rel.parts):
        return True
    return rel.name in ("__init__.py", "conftest.py") or rel.name.startswith("test_")


_DATA_STMT = (ast.Import, ast.ImportFrom, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.Pass)


def _is_declarative(stmt):
    """True si un statement top-level es declarativo (no lógica ejecutable): import, clase,
    asignación, o un literal suelto (docstring)."""
    return isinstance(stmt, _DATA_STMT) or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))


def _is_pure_data(pyfile):
    """True si el módulo es SOLO declaraciones de datos: sin funciones/métodos (ningún FunctionDef en
    todo el árbol) Y sin lógica ejecutable a nivel módulo (sin for/while/if/with/try ni llamadas
    sueltas). Esos módulos no tienen nada que gatear, así que no son 'código sin contrato'."""
    try:
        tree = ast.parse(Path(pyfile).read_text(encoding="utf-8"))
    except Exception:
        return False
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)):
        return False
    return all(_is_declarative(s) for s in tree.body)


def audit(root, skip_dirs=None):
    """Devuelve {py_files, contracts, orphans, ok}. orphans: .py de implementación sin contrato,
    relativos a root. `skip_dirs`: iterable extra de dirs a eximir ( además del default y del env
    `CCDD_ORPHAN_SKIP_DIR`); útil en repos mixtos donde fixtures/examples/etc. son soporte."""
    rootp = Path(root).resolve()
    skip = _skip_dirs(skip_dirs or ())
    targets = {(p.parent / fm["target"]).resolve()
               for p, fm in _contracts(root) if fm.get("kind") != "group" and "target" in fm}
    pys = [f for f in Path(root).rglob("*.py")
           if not _is_excluded(f.resolve().relative_to(rootp), skip)]
    orphans = sorted(_rel(f.resolve(), rootp) for f in pys
                     if f.resolve() not in targets and not _is_pure_data(f))
    return {"py_files": len(pys), "contracts": len(targets), "orphans": orphans, "ok": not orphans}


def _parse_args(argv):
    """Separa raíz (posicional) de `--skip-dir DIR` (repetible, = o espacio). Determinista."""
    roots, skip = [], []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--skip-dir" and i + 1 < len(argv):
            skip.append(argv[i + 1]); i += 2
        elif a.startswith("--skip-dir="):
            skip.append(a.split("=", 1)[1]); i += 1
        else:
            roots.append(a); i += 1
    return (roots[0] if roots else "."), skip


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root, skip = _parse_args(sys.argv[1:])
    res = audit(root, skip)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
