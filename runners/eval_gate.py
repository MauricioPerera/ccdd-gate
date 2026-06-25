#!/usr/bin/env python3
"""eval_gate.py — veredicto DETERMINISTA (Tier 1, sin LLM) de un EVAL-CONTRACT sobre output NO
determinista. El pilar que le faltaba a ccdd-gate: el gate de complejidad/tests verifica CÓDIGO;
este verifica el COMPORTAMIENTO de un agente cuya salida es texto/JSON.

  0) el eval-contract está bien formado (campos requeridos + budget)
  1) los casos están CONGELADOS: sus bytes coinciden con cases_sha256 (firma humana, anti-ablande)
  2) se corre el agente sobre cada caso y se aplican los checks deterministas (eval_checks):
     schema, contención, citas/groundedness (anti-alucinación), PII, trayectoria.
PASS solo si: casos intactos + pass_rate ≥ budget + violaciones duras ≤ budget. Idéntico corrida
a corrida. El juez LLM (Tier 2) es OPT-IN y vive en eval_judge.py / judge_audit.py; este gate no
llama a ningún LLM.

Uso:  python eval_gate.py eval.md
Exit: 0 PASS · 1 FAIL · 2 contrato/casos inválidos."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint     # noqa: E402  (split_front_matter)
import eval_checks  # noqa: E402

REQUIRED = ["eval", "intent", "target", "agent_entry", "dataset", "budget"]
DEFAULT_CHECKS = ["schema", "must_contain", "forbid_contains", "must_cite",
                  "groundedness", "no_pii", "trajectory"]


def _invalid(stage, detail, **extra):
    return {"verdict": "INVALID", "stage": stage, "detail": detail, **extra}


# El dataset se congela sobre bytes NORMALIZADOS a LF: byte-sensible al contenido pero estable
# entre plataformas (un checkout CRLF no invalida la firma). Mismo criterio para gate y approve.
def dataset_digest(path):
    norm = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _validate_contract(fm):
    missing = [k for k in REQUIRED if k not in fm]
    if missing:
        return _invalid("contract", f"eval-contract incompleto, faltan: {missing}")
    if not isinstance(fm.get("budget"), dict):
        return _invalid("contract", "budget debe ser un mapa")
    return None


# gate 1 — casos congelados (firma humana, determinista). Si el contrato exige aprobación, los
# bytes del dataset deben coincidir con el hash que firmó el humano (approve_eval_cases.py).
def _gate_cases_approval(fm, cases):
    if not cases.exists():
        return _invalid("cases", f"dataset no existe: {fm['dataset']}")
    if not fm.get("require_cases_approval"):
        return None
    actual = dataset_digest(cases)
    approved = fm.get("cases_sha256")
    if not approved:
        return _invalid("cases-approval", "casos sin aprobar (falta cases_sha256). Firma con approve_eval_cases.py.",
                        cases_sha256_actual=actual)
    if actual != approved:
        return _invalid("cases-approval", "los casos cambiaron desde la aprobación (hash no coincide). Re-aprueba.",
                        approved=approved, actual=actual)
    return None


def _load_jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _load_agent(target, entry):
    spec = importlib.util.spec_from_file_location(target.stem, target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, entry)


def _load_schema(p, fm):
    s = fm.get("schema")
    if not s:
        return None
    sp = p.parent / s
    return json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else None


def _eval_case(agent_fn, case, enabled, schema):
    try:
        output = agent_fn(case.get("input") or {})
    except Exception as e:
        return {"id": case.get("id"), "violations": [{"check": "run", "detail": f"el agente lanzó: {e}", "hard": True}]}
    return {"id": case.get("id"), "violations": eval_checks.run_checks(output, case, enabled, schema)}


def _verdict(fm, results):
    total = len(results)
    passed = sum(1 for r in results if not r["violations"])
    hard = sum(1 for r in results for v in r["violations"] if v.get("hard"))
    pass_rate = passed / total if total else 0.0
    budget = fm["budget"]
    rate_min = budget.get("pass_rate_min", 1.0)
    hard_max = budget.get("forbidden_violations_max", 0)
    ok = total > 0 and pass_rate >= rate_min and hard <= hard_max
    return {"verdict": "PASS" if ok else "FAIL", "stage": "tier1-checks",
            "cases": total, "passed": passed, "pass_rate": round(pass_rate, 4),
            "hard_violations": hard,
            "budget": {"pass_rate_min": rate_min, "forbidden_violations_max": hard_max},
            "failing": [r for r in results if r["violations"]][:20]}


def gate(eval_path):
    p = Path(eval_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return _invalid("contract", "sin front-matter YAML (--- ... ---)")
    bad = _validate_contract(fm)
    if bad:
        return bad
    cases_path = p.parent / fm["dataset"]
    bad = _gate_cases_approval(fm, cases_path)
    if bad:
        return bad
    target = p.parent / fm["target"]
    if not target.exists():
        return {"verdict": "FAIL", "stage": "agent", "detail": f"target no existe: {fm['target']}"}
    try:
        agent_fn = _load_agent(target, fm["agent_entry"])
    except Exception as e:
        return {"verdict": "FAIL", "stage": "agent", "detail": f"no se pudo cargar el agente: {e}"}
    enabled = fm.get("deterministic_checks") or DEFAULT_CHECKS
    schema = _load_schema(p, fm)
    results = [_eval_case(agent_fn, c, enabled, schema) for c in _load_jsonl(cases_path)]
    return _verdict(fm, results)


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print("uso: python eval_gate.py eval.md", file=sys.stderr)
        return 2
    v = gate(sys.argv[1])
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["verdict"] == "PASS" else (2 if v["verdict"] == "INVALID" else 1)


if __name__ == "__main__":
    sys.exit(main())
