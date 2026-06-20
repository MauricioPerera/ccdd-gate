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
    if not Path(cwd).is_dir():
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": f"el cwd de tests no existe: {cwd}"}
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


# --- Gate de integración (contratos de GRUPO) -------------------------------------------------
# Un contrato con `kind: group` compone funciones (u otros grupos) hijas. PASS solo si TODAS las
# hijas pasan su propio gate Y los tests de integración (la composición ensamblada) pasan. Es
# recursivo: una hija puede ser otro grupo, modelando spec -> task -> función. Determinista.
MAX_GROUP_DEPTH = 10


def _resolve_group_cwd(fm, group_dir):
    tc = fm.get("test_cwd")
    return str((group_dir / tc).resolve()) if tc else str(group_dir)


def _gate_children(fm, group_dir, depth):
    children = fm.get("children")
    if not isinstance(children, list) or not children:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": "un contrato 'group' requiere 'children' (lista no vacía)"}
    for child in children:
        cp = group_dir / child
        if not cp.exists():
            return {"verdict": "INVALID", "stage": "integration-contract",
                    "detail": f"contrato hijo no existe: {child}"}
        v = gate(str(cp), depth + 1)
        if v.get("verdict") != "PASS":
            return {"verdict": "FAIL", "stage": "integration-children",
                    "failed_child": child, "child_verdict": v}
    return None


def _gate_integration_tests(fm, group_dir):
    cmd_str = fm.get("integration_test_command")
    if not cmd_str:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": "un contrato 'group' requiere integration_test_command"}
    itests = fm.get("integration_tests")
    if itests and not (group_dir / itests).exists():
        return {"verdict": "FAIL", "stage": "integration-tests",
                "detail": f"integration_tests no existe: {itests}"}
    cwd = _resolve_group_cwd(fm, group_dir)
    if not Path(cwd).is_dir():
        return {"verdict": "FAIL", "stage": "integration-tests", "detail": f"el cwd de integración no existe: {cwd}"}
    r = subprocess.run(shlex.split(cmd_str), cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        return {"verdict": "FAIL", "stage": "integration-tests", "cwd": cwd,
                "output": (r.stderr or r.stdout or "")[-800:]}
    return None


# Spec compartida (zero-dep): un grupo declara las specs que CONSUME (`conforms_to`) o PRODUCE
# (`produces`). El gate verifica que existan y estén BIEN FORMADAS. La alineación backend<->front
# se garantiza porque ambos apuntan al MISMO archivo (misma verdad). La conformidad de COMPORTAMIENTO
# (¿la API servida cumple el OpenAPI?) es el integration_test_command (validador pluggable, opcional).
def _spec_wellformed(path):
    if not path.exists():
        return f"spec compartida no existe: {path.name}"
    suf = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
        if suf in (".yaml", ".yml"):
            import yaml
            yaml.safe_load(text)
        elif suf == ".json":
            json.loads(text)
    except Exception as e:
        return f"spec compartida mal formada ({path.name}): {e}"
    return None


def _gate_spec_conformance(fm, group_dir):
    refs = list(fm.get("conforms_to") or []) + list(fm.get("produces") or [])
    for ref in refs:
        problem = _spec_wellformed(group_dir / ref)
        if problem:
            return {"verdict": "FAIL", "stage": "integration-spec", "detail": problem}
    return None


def integration_gate(group_path, fm, depth=0):
    if depth > MAX_GROUP_DEPTH:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": f"recursión de grupos > {MAX_GROUP_DEPTH}; ¿ciclo en children?"}
    missing = [k for k in ("task", "intent", "children", "integration_test_command") if k not in fm]
    if missing:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": f"contrato 'group' incompleto, faltan: {missing}"}
    group_dir = Path(group_path).parent
    return (_gate_children(fm, group_dir, depth)
            or _gate_spec_conformance(fm, group_dir)
            or _gate_integration_tests(fm, group_dir)
            or {"verdict": "PASS", "stage": "integration-all", "children": fm["children"]})


def gate(task_path, _depth=0):
    p = Path(task_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if any(f["level"] == "error" for f in tc_lint.lint(task_path)):
        return {"verdict": "INVALID", "stage": "contract",
                "detail": "el task-contract no lintea (corre tc_lint.py para el detalle)"}
    if fm.get("kind") == "group":
        return integration_gate(task_path, fm, _depth)
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
