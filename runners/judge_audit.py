#!/usr/bin/env python3
"""judge_audit.py — fuerza/deriva del JUEZ (análogo a mutation_audit, que mide la fuerza del
oráculo). Corre el juez Tier 2 sobre los casos que llevan golden_judgment (atestado por humano) y
mide el ACUERDO (verdicts que coinciden / total). Si el acuerdo < judge.agreement_min, falla el
JUEZ — no el agente: un juez que no reproduce el criterio humano no es de fiar, y por tanto sus
veredictos sobre casos sin golden no cuentan.

Determinista con el provider 'stub' (acuerdo 1.0 por construcción: ejercita la mecánica offline).
Con 'openai' mide el acuerdo real del modelo pinneado contra el golden set.

Uso:  python judge_audit.py eval.md [--provider openai --api-url http://localhost:11434/v1]
Exit: 0 ok (juez de fiar) · 1 acuerdo insuficiente · 2 error."""
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


def audit(eval_path, provider="stub", api_url=""):
    p = Path(eval_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return {"ok": False, "detail": "sin front-matter YAML (--- ... ---)"}
    missing = [k for k in ("dataset", "target", "agent_entry") if not fm.get(k)]
    if missing:
        return {"ok": False, "detail": f"eval-contract incompleto, faltan: {missing}"}
    cases = eval_gate._load_jsonl(p.parent / fm["dataset"])
    agent_fn = eval_gate._load_agent(p.parent / fm["target"], fm["agent_entry"])
    judge_cfg = fm.get("judge") or {}
    rubric = _load_rubric(p, fm)
    golden = [c for c in cases if c.get("golden_judgment")]
    details, agree = [], 0
    for c in golden:
        try:
            output = agent_fn(c.get("input") or {})
        except Exception:
            output = {}
        v = eval_judge.judge(output, c, rubric, provider, judge_cfg.get("model", ""), api_url)
        expected = c["golden_judgment"].get("verdict")
        match = v.get("verdict") == expected
        agree += 1 if match else 0
        details.append({"id": c.get("id"), "judge": v.get("verdict"), "golden": expected, "match": match})
    n = len(golden)
    agreement = agree / n if n else 0.0
    minimum = judge_cfg.get("agreement_min", 0.85)
    return {"golden_cases": n, "agreement": round(agreement, 4), "agreement_min": minimum,
            "provider": provider, "ok": n > 0 and agreement >= minimum, "details": details}


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
