#!/usr/bin/env python3
"""audit_annotations.py — scan PROYECTO-wide del gate de anotaciones. Determinista, zero-dep.

Corre el check gate3-annotations (nombres usados en anotaciones sin importar/definir) sobre TODOS
los targets de contratos de función del proyecto, no solo los del diff. El gate por-función solo
toca los contratos AFECTADOS por un PR, así que un bug de anotación en código no tocado se cuela;
este scan lo caza project-wide. Es el bug que el runtime (Python 3.14 lazy annotations) enmascara.

Para CI de proyectos CCDD; exit 1 si hay alguna falla.
Uso:  python audit_annotations.py [raíz]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_composition import _contracts, _rel  # noqa: E402
import task_gate  # noqa: E402


# El resultado de _gate_annotations para un target depende SOLO del archivo y de `language` (el
# único campo de `fm` que usa). En repos donde N contratos apuntan al mismo target, la versión
# ingenua re-leía y re-parseaba (AST) el archivo una vez por contrato. Esta cache memoiza por
# (target resuelto, language): leer+parsear+walk UNA vez por target único, sin cambiar el resultado
# ni el orden de failures (la cache es pura memoización, no reordena la iteración de _contracts).
_CACHE_MISS = object()


def audit(root):
    """Devuelve {checked, failures, ok}. failures: targets con nombres de anotación sin resolver."""
    rootp = Path(root).resolve()
    checked, fails = 0, []
    cache = {}  # (resolved_tgt, lang) -> resultado de _gate_annotations (o None)
    for p, fm in _contracts(root):
        if fm.get("kind") == "group" or "target" not in fm:
            continue
        tgt = p.parent / fm["target"]
        if not tgt.exists():
            continue
        checked += 1
        key = (tgt.resolve(), (fm.get("language") or "python").lower())
        r = cache.get(key, _CACHE_MISS)
        if r is _CACHE_MISS:
            r = task_gate._gate_annotations(fm, tgt)
            cache[key] = r
        if r:
            fails.append({"target": _rel(tgt.resolve(), rootp), "detail": r["detail"]})
    return {"checked": checked, "failures": fails, "ok": not fails}


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
