#!/usr/bin/env python3
"""pre_complexity_runner.py — runner del contrato `pre-complexity-agent` (CCDD L3).

Flujo:  lint contrato -> assemble (guardrails) -> [verificar API key] -> API Anthropic
        -> separar texto/JSON -> reporte -> exit.

No reimplementa lint, assemble ni guardrails: invoca ccdd.py por subprocess.

Exit:  0 análisis sin señales CRÍTICA · 1 con señales CRÍTICA
       2 guardrail abortó (sin llamada API) · 3 error de configuración

Nota (tensión de CONTRACT.md §7): el criterio "exit 1 sin --json" exige conocer si hay
CRÍTICA, lo que requiere datos estructurados. Se pide SIEMPRE un bloque ```json al modelo
y se parsea para el verdicto (sin regex sobre texto libre). analysis_report.json solo se
ESCRIBE con --json. El texto libre va siempre a stdout.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pre_complexity_helpers as H  # noqa: E402

HERE = Path(__file__).resolve().parent
CCDD = HERE.parent / "ccdd.py"
CONTRACT = HERE.parent / "contracts" / "pre-complexity-agent"
CONTRACT_VERSION = "0.3"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 4000

JSON_REQ = (
    "\n\n---\nAdemás del análisis en texto anterior, al final emite UN ÚNICO bloque ```json "
    "con esta forma: {\"signals\": [{\"severity\", \"location\", \"description\", \"type\", "
    "\"prediction\", \"classification\", \"redesign_suggestion\"}], \"summary\": "
    "{\"dominant_complexity\", \"recommendation\", \"estimated_cost_of_ignoring\"}}. "
    "severity ∈ {CRÍTICA, ALTA, MEDIA, INFO}. No agregues texto después del bloque."
)


def fail(code, msg):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def ccdd(*args):
    # Forzar UTF-8 en el hijo (en Windows el stdio por defecto no es UTF-8 y rompe el decode).
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(CCDD), *args], env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def guardrail_onfail():
    import yaml
    c = yaml.safe_load((CONTRACT / "context.yaml").read_text(encoding="utf-8"))
    return {g["id"]: g.get("on_fail") for g in c["contract"].get("guardrails", [])}


def call_llm(provider, model, system, user):
    if provider == "ollama":
        import urllib.request
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        body = json.dumps({"model": model, "stream": False, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}]}).encode("utf-8")
        req = urllib.request.Request(host + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))["message"]["content"]
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=model, max_tokens=MAX_OUTPUT_TOKENS,
                                 system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="pre_complexity_runner",
                                 description="Análisis preventivo de complejidad sobre un artefacto de diseño.")
    ap.add_argument("--input", required=True, help="artefacto de diseño (txt, md) — REQUERIDO")
    ap.add_argument("--domain", help="contexto de dominio opcional")
    ap.add_argument("--patterns", help="patrones del proyecto opcionales")
    ap.add_argument("--adr", help="historial de decisiones opcional")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "ollama"],
                    help="backend de inferencia (ollama vía API local, httpx/urllib — §3)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    return ap.parse_args(argv)


def build_inputs(a):
    inp = Path(a.input)
    if not inp.exists():
        fail(3, f"input no encontrado: {a.input}")
    inputs = {"design_document": inp.read_text(encoding="utf-8")}
    for key, path in (("domain_context", a.domain), ("project_patterns", a.patterns),
                      ("decision_history", a.adr)):
        if path:
            p = Path(path)
            if not p.exists():
                fail(3, f"archivo no encontrado: {path}")
            inputs[key] = p.read_text(encoding="utf-8")
    return inp, inputs


def _utf8():
    for _s in (sys.stdout, sys.stderr):   # emitir UTF-8 (el análisis lleva → ✓ etc.)
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def assemble_and_export(a, inputs):
    """assemble + guardrails deterministas + export del payload (vía ccdd.py).
    fail() ante cualquier corte. Devuelve (payload, triggered, auto)."""
    last = CONTRACT / "last-assembly.json"
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(inputs, tmp, ensure_ascii=False)
        tmp.close()
        r = ccdd("assemble", str(CONTRACT), "--inputs", tmp.name)
        if r.returncode == 2:  # un slot crítico no entra (p.ej. design_document < min_tokens)
            fail(3, "análisis insuficiente / ensamblado inválido:\n" + (r.stdout or "").strip())
        verdict = (json.loads(last.read_text(encoding="utf-8"))["verdict"]
                   if last.exists() else {"passed": r.returncode == 0, "guardrails": []})
        onfail = guardrail_onfail()
        triggered = [g["id"] for g in verdict.get("guardrails", []) if not g["passed"]]
        aborted = [g for g in triggered if onfail.get(g) == "abort"]
        if aborted or not verdict.get("passed", True):
            fail(2, "guardrail abortó (sin llamada API): " + ", ".join(aborted or triggered))
        auto = [H.auto_signal(g) for g in triggered if onfail.get(g) == "reroute"]
        if a.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            fail(3, "ANTHROPIC_API_KEY no está en el entorno (requerida antes de llamar al modelo)")
        r = ccdd("export", str(CONTRACT), "--format", "anthropic", "--inputs", tmp.name)
        if r.returncode != 0:
            fail(3, "export del contexto falló:\n" + (r.stderr or r.stdout or ""))
        payload = json.loads(r.stdout)
    finally:
        os.unlink(tmp.name)
        last.unlink(missing_ok=True)  # no dejar artefacto de runtime en el directorio del contrato
    return payload, triggered, auto


def run(argv=None):
    _utf8()
    a = parse_args(argv if argv is not None else sys.argv[1:])
    if not CCDD.exists():
        fail(3, f"no se encontró el engine ccdd.py en {CCDD}")
    r = ccdd("lint", str(CONTRACT))  # el runner no opera con un contrato inválido
    if r.returncode != 0:
        fail(3, "el contrato no lintea (abortar):\n" + (r.stdout or "") + (r.stderr or ""))
    inp, inputs = build_inputs(a)
    payload, triggered, auto = assemble_and_export(a, inputs)
    model = a.model or payload.get("model", DEFAULT_MODEL)
    raw = call_llm(a.provider, model, payload["system"], payload["messages"][0]["content"] + JSON_REQ)
    free_text, parsed = H.split_text_and_json(raw)
    print(free_text)  # texto libre del análisis -> stdout SIEMPRE
    signals = ((parsed or {}).get("signals", []) or []) + auto
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = H.build_report("pre-complexity-agent", CONTRACT_VERSION, str(inp), ts, parsed, signals,
                            triggered, "domain_context" in inputs)
    if a.as_json:
        Path("analysis_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if report["summary"]["critical"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(run())
