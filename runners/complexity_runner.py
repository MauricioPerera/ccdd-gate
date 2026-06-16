#!/usr/bin/env python3
"""complexity_runner.py — runner del contrato `complexity-agent` (CCDD L3, análisis POST-código).

Flujo:  métricas deterministas por AST (metrics.py) -> lint_results -> lint contrato ->
        assemble (guardrails) -> [credenciales] -> LLM -> separar texto/JSON -> reporte -> exit.

A diferencia del pre-complexity, alimenta el slot `lint_results` con NÚMEROS REALES medidos
del AST (ciclomática, anidamiento, params, longitud); el LLM razona ESENCIAL/ACCIDENTAL encima.
No reimplementa lint/assemble/guardrails: invoca ccdd.py por subprocess.

Exit:  0 sin hallazgos CRÍTICA · 1 con CRÍTICA · 2 guardrail abortó · 3 error de configuración
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
import pre_complexity_helpers as H  # noqa: E402  (capa de transformación compartida)
import metrics  # noqa: E402         (extractor AST determinista)

HERE = Path(__file__).resolve().parent
CCDD = HERE.parent / "ccdd.py"
CONTRACT = HERE.parent / "contracts" / "complexity-agent"
CONTRACT_VERSION = "0.3"
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 4000

JSON_REQ = (
    "\n\n---\nAdemás del análisis en texto anterior, al final emite UN ÚNICO bloque ```json "
    "con: {\"signals\": [{\"severity\", \"location\", \"description\", \"type\", \"prediction\", "
    "\"classification\", \"redesign_suggestion\"}], \"summary\": {\"dominant_complexity\", "
    "\"recommendation\", \"estimated_cost_of_ignoring\"}}. severity ∈ {CRÍTICA, ALTA, MEDIA, INFO}. "
    "No agregues texto después del bloque."
)


def fail(code, msg):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def ccdd(*args):
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
    if provider == "openai":  # OpenAI-compatible (LM Studio, vLLM, etc.)
        import urllib.request
        base = os.environ.get("OPENAI_BASE_URL", "http://localhost:1234/v1").rstrip("/")
        body = json.dumps({"model": model, "stream": False, "temperature": 0.2, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}]}).encode("utf-8")
        req = urllib.request.Request(base + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer local"})
        with urllib.request.urlopen(req, timeout=900) as resp:
            return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=model, max_tokens=MAX_OUTPUT_TOKENS,
                                 system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="complexity_runner",
                                 description="Análisis de complejidad sobre código ya implementado (post-código).")
    ap.add_argument("--input", required=True, help="archivo de código a analizar (.py) — REQUERIDO")
    ap.add_argument("--repo-map", dest="repo_map", help="grafo de dependencias opcional")
    ap.add_argument("--debt", help="historial de deuda técnica opcional")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "ollama", "openai"])
    ap.add_argument("--json", action="store_true", dest="as_json")
    return ap.parse_args(argv)


def build_inputs(a):
    inp = Path(a.input)
    if not inp.exists():
        fail(3, f"input no encontrado: {a.input}")
    # métricas deterministas -> slot lint_results (validado por el guardrail json_schema) Y base del gate
    det = metrics.extract(inp)
    inputs = {"code_under_review": inp.read_text(encoding="utf-8"),
              "lint_results": json.dumps(det, ensure_ascii=False)}
    for key, path in (("repo_map", a.repo_map), ("debt_history", a.debt)):
        if path:
            p = Path(path)
            if not p.exists():
                fail(3, f"archivo no encontrado: {path}")
            inputs[key] = p.read_text(encoding="utf-8")
    return inp, inputs, det


def _utf8():
    for _s in (sys.stdout, sys.stderr):
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
        if r.returncode == 2:
            fail(3, "ensamblado inválido (¿código demasiado corto para el piso del slot?):\n" + (r.stdout or "").strip())
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
        last.unlink(missing_ok=True)
    return payload, triggered, auto


def run(argv=None):
    _utf8()
    a = parse_args(argv if argv is not None else sys.argv[1:])
    if not CCDD.exists():
        fail(3, f"no se encontró el engine ccdd.py en {CCDD}")
    r = ccdd("lint", str(CONTRACT))
    if r.returncode != 0:
        fail(3, "el contrato no lintea (abortar):\n" + (r.stdout or "") + (r.stderr or ""))
    inp, inputs, det = build_inputs(a)
    payload, triggered, auto = assemble_and_export(a, inputs)

    # ── GATE DETERMINISTA: el veredicto/exit sale de las métricas AST sobre umbrales firmados,
    #    NO del LLM. Idéntico corrida a corrida (F1). El LLM es solo capa explicativa (advisory).
    gate_findings = det.get("findings", [])
    gate_critical = sum(1 for f in gate_findings if f.get("severity") == "CRÍTICA")
    gate_high = sum(1 for f in gate_findings if f.get("severity") == "ALTA")
    gate_verdict = "FAIL" if gate_critical else "PASS"

    model = a.model or payload.get("model", DEFAULT_MODEL)
    raw = call_llm(a.provider, model, payload["system"], payload["messages"][0]["content"] + JSON_REQ)
    free_text, parsed = H.split_text_and_json(raw)
    print(free_text)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {
        "contract": "complexity-agent", "contract_version": CONTRACT_VERSION,
        "timestamp": ts, "input_file": str(inp),
        "gate": {  # determinista — decide el exit code
            "verdict": gate_verdict, "critical": gate_critical, "high": gate_high,
            "source": "ast-metrics sobre thresholds firmados", "findings": gate_findings,
        },
        "advisory": {  # LLM — clasifica esencial/accidental y explica; NO decide el gate
            "model": model, "analysis": free_text,
            "signals": ((parsed or {}).get("signals", []) or []) + auto,
        },
        "guardrails_triggered": triggered,
        "verdict": gate_verdict,
    }
    if a.as_json:
        Path("analysis_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if gate_critical else 0


if __name__ == "__main__":
    raise SystemExit(run())
