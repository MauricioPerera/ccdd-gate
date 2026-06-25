#!/usr/bin/env python3
"""approve_eval_cases.py — el OK humano sobre el DATASET de evals CONGELADO. Espeja approve_tests.py.

El humano firma la versión exacta del dataset: graba su digest (sha256 sobre bytes LF) en el
front-matter del eval-contract como `cases_sha256`. A partir de ahí eval_gate sólo corre si los
bytes del dataset coinciden; cualquier cambio posterior invalida la aprobación. La firma es del
dataset, no del agente.

Uso:  python approve_eval_cases.py eval.md            # firma la versión actual del dataset
      python approve_eval_cases.py eval.md --check    # muestra estado, no escribe
Exit: 0 ok · 1 desincronizado/sin firmar (en --check) · 2 error."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402  (split_front_matter)
import eval_gate  # noqa: E402  (dataset_digest: mismo criterio que el gate)
from approve_tests import _set_line  # noqa: E402  (reusa el inserter de front-matter)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="approve_eval_cases", description="Firma humana del dataset de evals congelado.")
    ap.add_argument("eval")
    ap.add_argument("--check", action="store_true", help="sólo reportar estado, no firmar")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    p = Path(a.eval)
    raw = p.read_text(encoding="utf-8")
    fm, _ = tc_lint.split_front_matter(raw)
    dataset = p.parent / fm["dataset"]
    if not dataset.exists():
        print(f"dataset no existe: {fm['dataset']}", file=sys.stderr)
        return 2
    actual = eval_gate.dataset_digest(dataset)
    approved = fm.get("cases_sha256")
    if a.check:
        state = "FIRMADO-OK" if approved == actual else ("SIN-FIRMAR" if not approved else "DESINCRONIZADO")
        print(f"{state}  dataset={fm['dataset']}  actual={actual}  aprobado={approved}")
        return 0 if state == "FIRMADO-OK" else 1
    p.write_text(_set_line(raw, "cases_sha256", actual), encoding="utf-8")
    print(f"FIRMADO  {fm['dataset']}  cases_sha256={actual}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
