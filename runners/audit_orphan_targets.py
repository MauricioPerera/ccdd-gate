#!/usr/bin/env python3
"""audit_orphan_targets.py — destaca CÓDIGO FUERA DEL FLUJO DE CONTRATO. Determinista, sin LLM.

Lista los `.py` de implementación (excluye tests, `__init__.py`, `conftest.py`) que NO son el
`target` de ningún task-contract. Es código que entró sin contrato ni gate: el orquestador
escribiendo implementación directa (lo que la política prohíbe), glue sin verificar, o cruft
(paquetes mal ubicados). La versión determinista del "¿se implementó fuera del gate?".

Pensado para CI de proyectos construidos ENTERAMENTE con CCDD (donde todo .py de producción debería
ser el target de un contrato). NO se cablea al ci_gate de ccdd-gate mismo: ccdd-gate no se construye
sobre sí mismo, así que sus runners no son targets. exit 1 si hay huérfanos.

Uso:  python audit_orphan_targets.py [raíz]"""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_composition import _contracts, _rel  # noqa: E402

_SKIP = {".git", ".pytest_cache", "__pycache__", "node_modules", "tests"}


def _is_excluded(rel):
    """True si el .py (ruta RELATIVA a la raíz) NO es código de implementación (test/glue/cache).
    Se evalúa sobre la ruta relativa: si la raíz del proyecto está bajo un dir 'tests'/'.git'/etc.,
    NO debe excluir todo."""
    if any(part in _SKIP for part in rel.parts):
        return True
    return rel.name in ("__init__.py", "conftest.py") or rel.name.startswith("test_")


def _is_pure_data(pyfile):
    """True si el módulo NO define ninguna función/método (solo dataclasses, constantes, imports):
    una declaración de datos no tiene lógica que gatear, así que no es 'código sin contrato'."""
    try:
        tree = ast.parse(Path(pyfile).read_text(encoding="utf-8"))
    except Exception:
        return False
    return not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))


def audit(root):
    """Devuelve {py_files, contracts, orphans, ok}. orphans: .py de implementación sin contrato,
    relativos a root."""
    rootp = Path(root).resolve()
    targets = {(p.parent / fm["target"]).resolve()
               for p, fm in _contracts(root) if fm.get("kind") != "group" and "target" in fm}
    pys = [f for f in Path(root).rglob("*.py") if not _is_excluded(f.resolve().relative_to(rootp))]
    orphans = sorted(_rel(f.resolve(), rootp) for f in pys
                     if f.resolve() not in targets and not _is_pure_data(f))
    return {"py_files": len(pys), "contracts": len(targets), "orphans": orphans, "ok": not orphans}


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    res = audit(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
