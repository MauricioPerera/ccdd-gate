#!/usr/bin/env python3
"""task_gate.py — veredicto DETERMINISTA unificado de una task. Sin LLM.
  0) el contrato lintea (tc_lint)
  1) gate complejidad: la función implementada ≤ budget de la task
  2) gate corrección: los property-tests congelados pasan
PASS solo si las tres. Idéntico corrida a corrida.

Uso:  python task_gate.py task.md
Exit: 0 PASS · 1 FAIL · 2 contrato inválido."""
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402
import metrics_backends  # noqa: E402

BUDGET_KEY = {"cyclomatic": "cyclomatic_max", "nesting_depth": "nesting_max",
              "parameter_count": "params_max", "function_length": "lines_max"}


# gate 0.5 — OK humano (determinista, a prueba de manipulación): si el contrato exige
# aprobación, los bytes de los tests deben coincidir con el hash que firmó el humano.
def _gate_test_approval(fm, tests):
    if not fm.get("require_test_approval"):
        return None
    if not tests.exists():
        return {"verdict": "INVALID", "stage": "test-approval", "detail": f"tests no existe: {fm['tests']}"}
    actual = hashlib.sha256(tests.read_bytes()).hexdigest()
    approved = fm.get("tests_sha256")
    if not approved:
        return {"verdict": "INVALID", "stage": "test-approval",
                "detail": "tests sin aprobar (falta tests_sha256). Revisa con test_audit.py y firma con approve_tests.py.",
                "tests_sha256_actual": actual}
    if actual != approved:
        return {"verdict": "INVALID", "stage": "test-approval",
                "detail": "los tests cambiaron desde la aprobación (hash no coincide). Re-audita y re-aprueba.",
                "approved": approved, "actual": actual}
    return None


# CWD para correr los tests. Default histórico (a prueba de regresión): la carpeta del target.
# Si el contrato declara `test_cwd`, se resuelve relativo al directorio del contrato (igual que
# target/tests), permitiendo correr los tests desde la raíz del proyecto sin paths absolutos.
def _resolve_test_cwd(fm, target, contract_dir):
    tc = fm.get("test_cwd")
    if tc:
        return str((contract_dir / tc).resolve())
    return str(target.parent)


# gate 1 — property-tests congelados (determinista) y sintaxis
def _gate_run_tests(fm, target, tests, contract_dir):
    if not tests.exists():
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": f"tests no existe: {fm['tests']}"}
    test_cmd_str = fm.get("test_command")
    # shlex.split + sin shell: comando portable y determinista. Respeta comillas (simples y dobles)
    # igual en todas las plataformas, a diferencia de shell=True que en Windows usa cmd.exe y rompe
    # las comillas simples (causa de los fallos con rutas con espacios).
    cmd = shlex.split(test_cmd_str) if test_cmd_str else [sys.executable, str(tests.resolve())]
    cwd = _resolve_test_cwd(fm, target, contract_dir)
    r = subprocess.run(cmd, cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        # `cwd` en el detalle: si el comando no encuentra el test, el autor ve desde DÓNDE corrió
        # (los paths del test_command son relativos a esto) y puede ajustar test_cwd sin adivinar.
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": "property-tests o sintaxis fallaron",
                "cwd": cwd, "output": (r.stderr or r.stdout or "")[-800:]}
    return None


# gate 2 — complejidad ≤ budget de la task
def _gate_complexity(fm, target, fn_name, budget):
    if not target.exists():
        return {"verdict": "FAIL", "stage": "gate2-complexity", "detail": f"target no existe: {fm['target']}"}
    fns = {f["function"]: f for f in metrics_backends.functions_metrics(target.read_text(encoding="utf-8"), language=fm.get("language"), filename=str(target))}
    if fn_name not in fns:
        return {"verdict": "FAIL", "stage": "gate2-complexity", "detail": f"la función '{fn_name}' no está en {fm['target']}"}
    m = fns[fn_name]
    over = [f"{metric}={m[metric]} > {key}={budget[key]}"
            for metric, key in BUDGET_KEY.items()
            if isinstance(budget.get(key), int) and m[metric] > budget[key]]
    if over:
        return {"verdict": "FAIL", "stage": "gate2-complexity", "function": fn_name, "over_budget": over}
    return {"verdict": "PASS", "stage": "all", "function": fn_name,
            "metrics": {k: m[k] for k in BUDGET_KEY}, "budget": budget}


def gate(task_path):
    p = Path(task_path)
    if any(f["level"] == "error" for f in tc_lint.lint(task_path)):
        return {"verdict": "INVALID", "stage": "contract",
                "detail": "el task-contract no lintea (corre tc_lint.py para el detalle)"}
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    target = p.parent / fm["target"]
    tests = p.parent / fm["tests"]
    fn_name, _n = tc_lint.parse_sig(fm["signature"], fm.get("language"))

    return (_gate_test_approval(fm, tests)
            or _gate_run_tests(fm, target, tests, p.parent)
            or _gate_complexity(fm, target, fn_name, fm["budget"]))


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print("uso: python task_gate.py task.md", file=sys.stderr)
        return 2
    v = gate(sys.argv[1])
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["verdict"] == "PASS" else (2 if v["verdict"] == "INVALID" else 1)


if __name__ == "__main__":
    sys.exit(main())
