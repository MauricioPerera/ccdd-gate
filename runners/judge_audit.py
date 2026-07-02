#!/usr/bin/env python3
"""judge_audit.py — fuerza/deriva del JUEZ (análogo a mutation_audit, que mide la fuerza del
oráculo). Corre el juez Tier 2 sobre los casos que llevan golden_judgment (atestado por humano) y
mide el ACUERDO (verdicts que coinciden / total). Si el acuerdo < judge.agreement_min, falla el
JUEZ — no el agente: un juez que no reproduce el criterio humano no es de fiar, y por tanto sus
veredictos sobre casos sin golden no cuentan.

Determinista con el provider 'stub' (acuerdo 1.0 por construcción: ejercita la mecánica offline).
Con 'openai' mide el acuerdo real del modelo pinneado contra el golden set.

IMPORTANTE: una auditoría con provider 'stub' NO habilita Tier 2 — el acuerdo 1.0 es tautológico
(stub devuelve el golden_judgment del caso). stub solo ejercita la mecánica; para habilitar Tier 2
hace falta un provider real (openai) cuyo acuerdo contra el golden set alcance agreement_min.

Uso:  python judge_audit.py eval.md [--provider openai --api-url http://localhost:11434/v1]
Exit: 0 ok (juez de fiar, auditoría válida) · 1 acuerdo insuficiente / stub · 2 error."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint    # noqa: E402
import eval_gate  # noqa: E402  (reusa _load_jsonl / _load_agent)
import eval_judge  # noqa: E402


def _load_rubric(p, fm):
    """Rúbrica del juez: el system.txt del contrato `rubric` (relativo al eval o bajo contracts/)."""
    rb = fm.get("rubric")
    if rb:
        local = p.parent / rb
        d = local if local.exists() else (Path(__file__).resolve().parents[1] / "contracts" / rb)
        sysf = Path(d) / "system.txt"
        if sysf.exists():
            return sysf.read_text(encoding="utf-8")
    return "Evalúa la coherencia y la utilidad de la respuesta del agente."


def _score_case(judge, agent_fn, c):
    """Output del agente + veredicto del juez vs golden -> (judge_verdict, golden_verdict, match).
    Un agente que lanza no tumba la auditoría: se cuenta como output vacío (veredicto del juez sobre
    nada, casi siempre discordante con el golden)."""
    try:
        output = agent_fn(c.get("input") or {})
    except Exception:
        output = {}
    v = judge(output, c)
    expected = c["golden_judgment"].get("verdict")
    return v.get("verdict"), expected, v.get("verdict") == expected


def _missing_keys(fm):
    return [k for k in ("dataset", "target", "agent_entry") if not fm.get(k)]


def audit(eval_path, provider="stub", api_url="", judge_fn=None):
    p = Path(eval_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return {"ok": False, "detail": "sin front-matter YAML (--- ... ---)"}
    missing = _missing_keys(fm)
    if missing:
        return {"ok": False, "detail": f"eval-contract incompleto, faltan: {missing}"}
    cases = eval_gate._load_jsonl(p.parent / fm["dataset"])
    agent_fn = eval_gate._load_agent(p.parent / fm["target"], fm["agent_entry"])
    judge_cfg = fm.get("judge") or {}
    rubric = _load_rubric(p, fm)
    golden = [c for c in cases if c.get("golden_judgment")]
    # judge_fn solo es para tests que simulan un juez discrepante; en producción se usa eval_judge.judge.
    _judge = judge_fn or (lambda o, c: eval_judge.judge(o, c, rubric, provider,
                                                        judge_cfg.get("model", ""), api_url))
    details, agree = [], 0
    for c in golden:
        jv, gv, match = _score_case(_judge, agent_fn, c)
        agree += 1 if match else 0
        details.append({"id": c.get("id"), "judge": jv, "golden": gv, "match": match})
    return _audit_verdict(provider, len(golden), agree, judge_cfg.get("agreement_min", 0.85), details)


def _audit_verdict(provider, n, agree, minimum, details):
    """Compone el veredicto de auditoría. audit_valid = provider real (no stub) + acuerdo ≥ min.
    stub → audit_valid=False (acuerdo 1.0 tautológico, no habilita Tier 2) con nota explicativa."""
    agreement = agree / n if n else 0.0
    is_stub = provider == "stub"
    audit_valid = (not is_stub) and n > 0 and agreement >= minimum
    note = ("provider 'stub' solo ejercita la mecánica (acuerdo 1.0 tautológico); NO habilita Tier 2. "
            "Use un provider real (openai) y re-corra la auditoría.") if is_stub else None
    return {"golden_cases": n, "agreement": round(agreement, 4), "agreement_min": minimum,
            "provider": provider, "audit_valid": audit_valid, "ok": audit_valid,
            "note": note, "details": details}


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="judge_audit", description="Calibra el juez Tier 2 contra el golden set.")
    ap.add_argument("eval")
    ap.add_argument("--provider", default="stub", choices=sorted(eval_judge.PROVIDERS))
    ap.add_argument("--api-url", default="")
    a = ap.parse_args()
    r = audit(a.eval, a.provider, a.api_url)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())