#!/usr/bin/env python3
"""complexity_mcp.py — servidor MCP local (stdio, JSON-RPC 2.0) que expone el SUSTRATO
determinista + el rubric gobernado de los contratos CCDD. NO llama a ningún LLM: el cerebro
es el agente anfitrión (Claude Code/Cursor) que invoca estas tools.

Tools:
  measure_complexity(code, filename?)        -> métricas AST reales por función (sin LLM)
  complexity_rubric(agent?)                  -> system/policies/thresholds del contrato FIRMADO
  scan_guardrails(code, agent?)              -> guardrails deterministas del contrato (secretos, anidamiento)
  lint_task_contract(contract_text, test_code?) -> tc_lint determinista sobre un task-contract en memoria
                                                 (anti-desvarío del modelo grande que lo autora)

Transporte: MCP stdio = mensajes JSON-RPC delimitados por salto de línea.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics    # noqa: E402
import tc_lint    # noqa: E402

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent / "contracts"
DEFAULT_AGENT = "complexity-agent"
AGENTS = {"complexity-agent", "pre-complexity-agent", "task-author-agent"}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TOOLS = [
    {
        "name": "measure_complexity",
        "description": "Mide complejidad por AST de Python (ciclomática, anidamiento, nº de parámetros, "
                       "longitud) por función. Determinista, sin LLM. Devuelve valores reales y si superan el umbral firmado.",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string", "description": "Código Python a medir."},
            "filename": {"type": "string", "description": "Nombre lógico del archivo (opcional)."}}},
    },
    {
        "name": "complexity_rubric",
        "description": "Devuelve el criterio GOBERNADO (system + policies + thresholds) del contrato CCDD "
                       "firmado, para que TÚ (el agente) analices con el criterio del equipo, no el tuyo.",
        "inputSchema": {"type": "object", "properties": {
            "agent": {"type": "string", "enum": sorted(AGENTS),
                      "description": "complexity-agent (post-código) o pre-complexity-agent (diseño)."}}},
    },
    {
        "name": "scan_guardrails",
        "description": "Aplica los guardrails deterministas del contrato (secretos, anidamiento profundo) "
                       "al código. Sin LLM. Devuelve cuáles dispararon y su on_fail.",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string"},
            "agent": {"type": "string", "enum": sorted(AGENTS)}}},
    },
    {
        "name": "lint_task_contract",
        "description": "Valida un TASK-CONTRACT (front-matter YAML + cuerpo Markdown) con tc_lint determinista, "
                       "ANTES de emitirlo al implementador pequeño. Anti-desvarío del modelo grande que lo autora: "
                       "campos requeridos, intent atómico, firma válida (por lenguaje vía el campo opcional "
                       "'language' del front-matter; python con parser nativo, el resto por aridad genérica), "
                       "budget ≤ topes firmados, secciones obligatorias, regla de parada, tests congelados. Pasa "
                       "también test_code para validar que los property-tests existen y referencian la firma. "
                       "Sin LLM. Devuelve {ok, errors, findings}.",
        "inputSchema": {"type": "object", "required": ["contract_text"], "properties": {
            "contract_text": {"type": "string", "description": "El task-contract completo (--- yaml --- + cuerpo)."},
            "test_code": {"type": "string", "description": "Código de los property-tests congelados (opcional pero "
                          "recomendado: sin él la regla tc-tests-frozen falla)."}}},
    },
]


def _agent_dir(agent):
    a = agent if agent in AGENTS else DEFAULT_AGENT
    return CONTRACTS / a, a


def measure_complexity(args):
    return metrics.extract_source(args["code"], args.get("filename", "snippet.py"))


def complexity_rubric(args):
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    read = lambda f: (d / f).read_text(encoding="utf-8") if (d / f).exists() else ""
    return {"agent": a, "contract_dir": d.name,
            "system": read("system.txt"), "policies": read("policies.txt"),
            "thresholds": read("thresholds.txt"), "environment": read("env.txt")}


def scan_guardrails(args):
    import yaml
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    code = args["code"]
    c = yaml.safe_load((d / "context.yaml").read_text(encoding="utf-8"))
    results = []
    for g in c["contract"].get("guardrails", []):
        if g.get("type") != "regex_deny":
            continue
        fired = bool(re.search(g["pattern"], code, re.MULTILINE))
        results.append({"id": g["id"], "fired": fired, "on_fail": g.get("on_fail")})
    return {"agent": a, "guardrails": results,
            "blocked": any(r["fired"] and r["on_fail"] == "abort" for r in results)}


def lint_task_contract(args):
    """Lintea un task-contract en memoria. Escribe contrato (+ tests si vienen) a un tempdir
    para que las reglas que tocan el filesystem (tc-tests-frozen) funcionen, y corre tc_lint."""
    fm, _ = tc_lint.split_front_matter(args["contract_text"].replace("\r\n", "\n"))
    tests_name = (fm or {}).get("tests", "frozen_tests.py")
    with tempfile.TemporaryDirectory() as d:
        task = Path(d) / "task.md"
        task.write_text(args["contract_text"], encoding="utf-8")
        if "test_code" in args:
            (Path(d) / tests_name).write_text(args["test_code"], encoding="utf-8")
        findings = tc_lint.lint(task)
    errors = sum(1 for f in findings if f["level"] == "error")
    return {"ok": errors == 0, "errors": errors,
            "warnings": len(findings) - errors, "findings": findings,
            "tests_provided": "test_code" in args}


DISPATCH = {"measure_complexity": measure_complexity,
            "complexity_rubric": complexity_rubric,
            "scan_guardrails": scan_guardrails,
            "lint_task_contract": lint_task_contract}


def send(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_tools_call(mid, params):
    name = params["name"]
    fn = DISPATCH.get(name)
    if not fn:
        return send(mid, error={"code": -32601, "message": f"tool desconocida: {name}"})
    try:
        out = fn(params.get("arguments", {}))
    except Exception as e:
        return send(mid, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    return send(mid, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]})


def handle(msg):
    # ifs planos con return temprano (no elif): evita el artefacto de anidamiento del AST.
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return send(mid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "ccdd-complexity-mcp", "version": "0.1"}})
    if method == "tools/list":
        return send(mid, {"tools": TOOLS})
    if method == "tools/call":
        return handle_tools_call(mid, msg["params"])
    if mid is None:
        return None  # notificación (p.ej. notifications/initialized): no se responde
    return send(mid, error={"code": -32601, "message": f"método no soportado: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle(json.loads(line))


if __name__ == "__main__":
    main()
