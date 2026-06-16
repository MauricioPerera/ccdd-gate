#!/usr/bin/env python3
"""test_audit.py — auditoría ADVISORY (modelo grande) de los property-tests CONTRA el task-contract.

NO es un gate determinista: es la segunda pasada del modelo grande que escribió/revisó el contrato,
buscando incongruencias (el test asume algo que el contrato no dice, o lo contradice) y puntos ciegos
(invariante/ejemplo del contrato que NINGÚN test verifica, aserciones débiles, oráculo importado del
propio target). Su salida orienta al humano que da el OK; no decide PASS/FAIL.

Uso:  python test_audit.py task.md [--provider openai|anthropic|ollama] [--model ID]
Exit: 0 sin hallazgos · 1 con hallazgos (advisory) · 2 error de configuración.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint                              # noqa: E402
import pre_complexity_helpers as H          # noqa: E402
from complexity_runner import call_llm      # noqa: E402

SYSTEM = (
    "Eres un revisor adversarial de tests. Te doy un task-contract (prescriptivo) y el código de sus "
    "property-tests CONGELADOS. Tu trabajo: encontrar dónde los tests NO protegen el contrato. "
    "Dos categorías: 'incongruencia' (el test asume/exige algo que el contrato no dice o contradice) "
    "y 'punto_ciego' (un invariante o ejemplo del contrato que ningún test verifica, una aserción "
    "trivialmente satisfacible, o un oráculo importado del propio target en vez de independiente). "
    "No propongas reescribir el algoritmo. Responde SOLO con un bloque ```json al final."
)

JSON_REQ = (
    "\n\nEmite UN ÚNICO bloque ```json con: {\"findings\": [{\"kind\": \"incongruencia|punto_ciego\", "
    "\"severity\": \"alta|media|baja\", \"where\": \"<invariante/ejemplo/línea>\", \"detail\": \"...\", "
    "\"suggested_assertion\": \"<aserción concreta a añadir, o null>\"}], \"summary\": \"<1 frase>\"}. "
    "Si los tests cubren bien el contrato, devuelve findings: []."
)


def build_user(fm, body, test_src):
    return (f"## TASK-CONTRACT (front-matter)\n```yaml\n{json.dumps(fm, ensure_ascii=False, indent=2)}\n```\n"
            f"## TASK-CONTRACT (cuerpo)\n{body}\n\n"
            f"## PROPERTY-TESTS CONGELADOS ({fm.get('tests')})\n```python\n{test_src}\n```\n" + JSON_REQ)


def audit(task_path, provider, model):
    p = Path(task_path)
    fm, body = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    tests = p.parent / fm["tests"]
    if not tests.exists():
        return None, {"error": f"tests no existe: {fm['tests']}"}
    raw = call_llm(provider, model, SYSTEM, build_user(fm, body, tests.read_text(encoding="utf-8")))
    free, parsed = H.split_text_and_json(raw)
    return free, (parsed or {"findings": [], "summary": "(no se pudo parsear el JSON del modelo)", "raw": raw[-400:]})


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="test_audit", description="Auditoría advisory de tests vs task-contract.")
    ap.add_argument("task")
    ap.add_argument("--provider", default="openai", choices=["anthropic", "ollama", "openai"])
    ap.add_argument("--model", default="qwen/qwen3.6-35b-a3b")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    free, report = audit(a.task, a.provider, a.model)
    if report.get("error"):
        print(report["error"], file=sys.stderr)
        return 2
    out = {"task": Path(a.task).name, "advisory_model": a.model,
           "findings": report.get("findings", []), "summary": report.get("summary", "")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if out["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
