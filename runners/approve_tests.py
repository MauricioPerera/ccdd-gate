#!/usr/bin/env python3
"""approve_tests.py — el OK humano sobre los property-tests CONGELADOS.

El humano (tras leer la auditoría de test_audit.py) firma la versión exacta de los tests:
graba su sha256 en el front-matter del task como `tests_sha256`. A partir de ahí task_gate
sólo corre si los bytes de los tests coinciden con ese hash; cualquier cambio posterior
invalida la aprobación. La firma es de los tests, no de la implementación.

Uso:  python approve_tests.py task.md            # firma la versión actual de los tests
      python approve_tests.py task.md --check    # muestra estado, no escribe
Exit: 0 ok · 1 desincronizado/no firmado (en --check) · 2 error.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402  (split_front_matter)


def _set_line(text, key, value):
    """Inserta/reemplaza `key: value` dentro del primer bloque front-matter (--- ... ---)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("el task no empieza con front-matter '---'")
    close = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    newline = f'{key}: "{value}"\n'
    for i in range(1, close):
        if lines[i].lstrip().startswith(f"{key}:"):
            lines[i] = newline
            return "".join(lines)
    lines.insert(close, newline)
    return "".join(lines)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="approve_tests", description="Firma humana de los property-tests congelados.")
    ap.add_argument("task")
    ap.add_argument("--check", action="store_true", help="sólo reportar estado, no firmar")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    p = Path(a.task)
    raw = p.read_text(encoding="utf-8")
    fm, _ = tc_lint.split_front_matter(raw)
    tests = p.parent / fm["tests"]
    if not tests.exists():
        print(f"tests no existe: {fm['tests']}", file=sys.stderr)
        return 2
    import semantic_hash
    actual = semantic_hash.get_semantic_hash(tests.read_text(encoding="utf-8"), tests.suffix)
    approved = fm.get("tests_sha256")
    if a.check:
        state = "FIRMADO-OK" if approved == actual else ("SIN-FIRMAR" if not approved else "DESINCRONIZADO")
        print(f"{state}  tests={fm['tests']}  actual={actual}  aprobado={approved}")
        return 0 if state == "FIRMADO-OK" else 1
    p.write_text(_set_line(raw, "tests_sha256", actual), encoding="utf-8")
    print(f"FIRMADO  {fm['tests']}  tests_sha256={actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
