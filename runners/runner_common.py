#!/usr/bin/env python3
"""runner_common.py — capa compartida por los orquestadores L3 (complexity_runner y
pre_complexity_runner): driver determinista de ccdd.py (assemble + guardrails + export).
NO llama a ningún LLM. Parametrizada por el `ccdd` (callable al engine), el directorio de
`contract` y el `fail` del runner, para servir a ambos contratos sin duplicar lógica."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pre_complexity_helpers as H  # noqa: E402  (capa de transformación compartida)


def guardrail_onfail(contract):
    """Mapa {id_guardrail: on_fail} declarado en el context.yaml del contrato."""
    import yaml
    c = yaml.safe_load((contract / "context.yaml").read_text(encoding="utf-8"))
    return {g["id"]: g.get("on_fail") for g in c["contract"].get("guardrails", [])}


def _assembly_verdict(last, r):
    if last.exists():
        return json.loads(last.read_text(encoding="utf-8"))["verdict"]
    return {"passed": r.returncode == 0, "guardrails": []}


def _reroute_signals(triggered, onfail):
    return [H.auto_signal(g) for g in triggered if onfail.get(g) == "reroute"]


def _check_guardrails(last, r, contract, fail):
    """Devuelve (triggered, auto); aborta vía fail() si un guardrail corta o el ensamblado no pasó."""
    verdict = _assembly_verdict(last, r)
    onfail = guardrail_onfail(contract)
    triggered = [g["id"] for g in verdict.get("guardrails", []) if not g["passed"]]
    aborted = [g for g in triggered if onfail.get(g) == "abort"]
    if aborted or not verdict.get("passed", True):
        fail(2, "guardrail abortó (sin llamada API): " + ", ".join(aborted or triggered))
    return triggered, _reroute_signals(triggered, onfail)


def _export_payload(a, tmp_name, ccdd, contract, fail):
    """Export del contexto en formato anthropic; aborta vía fail() ante cualquier corte."""
    if a.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        fail(3, "ANTHROPIC_API_KEY no está en el entorno (requerida antes de llamar al modelo)")
    r = ccdd("export", str(contract), "--format", "anthropic", "--inputs", tmp_name)
    if r.returncode != 0:
        fail(3, "export del contexto falló:\n" + (r.stderr or r.stdout or ""))
    return json.loads(r.stdout)


def assemble_and_export(a, inputs, ccdd, contract, fail, invalid_msg):
    """assemble + guardrails deterministas + export del payload (vía ccdd.py). fail() ante
    cualquier corte. `invalid_msg` es el prefijo de error si el ensamblado no entra (rc==2).
    Devuelve (payload, triggered, auto)."""
    last = contract / "last-assembly.json"
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(inputs, tmp, ensure_ascii=False)
        tmp.close()
        r = ccdd("assemble", str(contract), "--inputs", tmp.name)
        if r.returncode == 2:
            fail(3, invalid_msg + "\n" + (r.stdout or "").strip())
        triggered, auto = _check_guardrails(last, r, contract, fail)
        payload = _export_payload(a, tmp.name, ccdd, contract, fail)
    finally:
        os.unlink(tmp.name)
        last.unlink(missing_ok=True)  # no dejar artefacto de runtime en el directorio del contrato
    return payload, triggered, auto
