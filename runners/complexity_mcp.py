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
import metrics    # noqa: E402  (registra el backend python)
import metrics_backends as mb  # noqa: E402
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
        "description": "Mide complejidad por función (ciclomática, anidamiento, nº de parámetros, longitud) "
                       "con el backend del LENGUAJE (python con AST nativo; otros lenguajes vía backend "
                       "registrado, enrutado por 'language' o por la extensión de 'filename'; default python). "
                       "Determinista, sin LLM. Devuelve valores reales y si superan el umbral firmado.",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string", "description": "Código a medir."},
            "filename": {"type": "string", "description": "Nombre lógico del archivo (opcional; su extensión "
                         "selecciona backend si no se pasa 'language')."},
            "language": {"type": "string", "description": "Lenguaje del backend (opcional; precede a la "
                         "extensión). Default python (back-compat)."}}},
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
        "description": "Aplica los guardrails deterministas al código: texto-puro compartidos (secretos), "
                       "estructurales calculados con el backend del LENGUAJE (anidamiento profundo, no por "
                       "regex de indentación) y específicos del lenguaje si existen (p. ej. no-eval). El "
                       "lenguaje se toma de 'language' o de la extensión de 'filename' (default python). "
                       "Sin LLM. Devuelve cuáles dispararon, su on_fail y el método (regex/backend).",
        "inputSchema": {"type": "object", "required": ["code"], "properties": {
            "code": {"type": "string"},
            "agent": {"type": "string", "enum": sorted(AGENTS)},
            "language": {"type": "string", "description": "Lenguaje (opcional; precede a la extensión)."},
            "filename": {"type": "string", "description": "Nombre de archivo (opcional; su extensión "
                         "selecciona lenguaje si no se pasa 'language')."}}},
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
    fname = args.get("filename", "snippet.py")
    try:
        backend = mb.get_backend(language=args.get("language"), filename=fname)
    except KeyError:
        return {"error": "sin backend de métricas para el lenguaje/extensión pedido",
                "language": args.get("language"), "filename": fname,
                "available_languages": mb.supported_languages()}
    return backend.extract_source(args["code"], fname)


def complexity_rubric(args):
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    read = lambda f: (d / f).read_text(encoding="utf-8") if (d / f).exists() else ""
    return {"agent": a, "contract_dir": d.name,
            "system": read("system.txt"), "policies": read("policies.txt"),
            "thresholds": read("thresholds.txt"), "environment": read("env.txt")}


# Guardrails ESTRUCTURALES: dependen de las métricas, no de un patrón de texto. Se calculan con
# el backend del lenguaje (no con el regex de indentación, que asume Python). id -> métrica/umbral.
STRUCTURAL_GUARDRAILS = {"deep-nesting": ("nesting_depth", mb.RED["nesting_depth"])}


def _lang_guardrails(language):
    """Guardrails específicos del lenguaje (opt-in) desde guardrails_lang.yaml. [] si no hay."""
    import yaml
    f = HERE / "guardrails_lang.yaml"
    if not f.exists():
        return []
    try:
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(language, [])
    except Exception:
        return []


# Mapa extensión -> lenguaje para seleccionar guardrails por lenguaje, INDEPENDIENTE de que
# exista un backend de métricas (los guardrails de texto/lenguaje aplican aunque no haya backend).
_EXT_LANG = {".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescript",
             ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
             ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby"}


def _resolve_language(args):
    """language explícito > lenguaje por la extensión de filename > default (python)."""
    if args.get("language"):
        return args["language"]
    fn = args.get("filename") or ""
    if "." in fn:
        return _EXT_LANG.get("." + fn.rsplit(".", 1)[1].lower(), mb.DEFAULT_LANGUAGE)
    return mb.DEFAULT_LANGUAGE


def _eval_structural(gid, code, language):
    """Evalúa un guardrail estructural con el backend del lenguaje. None si no hay backend o el
    código no parsea (el caller cae al regex del propio guardrail)."""
    metric, limit = STRUCTURAL_GUARDRAILS[gid]
    try:
        fns = mb.get_backend(language=language).measure(code)
    except Exception:
        return None
    return any(f[metric] >= limit for f in fns)


def scan_guardrails(args):
    import yaml
    d, a = _agent_dir(args.get("agent", DEFAULT_AGENT))
    code = args["code"]
    language = _resolve_language(args)
    c = yaml.safe_load((d / "context.yaml").read_text(encoding="utf-8"))
    results = []
    for g in list(c["contract"].get("guardrails", [])) + list(_lang_guardrails(language)):
        gid = g["id"]
        if gid in STRUCTURAL_GUARDRAILS:  # estructural: backend del lenguaje (no el regex)
            fired = _eval_structural(gid, code, language)
            if fired is not None:
                results.append({"id": gid, "fired": fired, "on_fail": g.get("on_fail"),
                                "method": "backend", "language": language})
                continue  # sin backend: cae al regex de abajo (degradación)
        if g.get("type") == "regex_deny":  # texto-puro compartido (secretos, no-eval, …) o fallback
            fired = bool(re.search(g["pattern"], code, re.MULTILINE))
            results.append({"id": gid, "fired": fired, "on_fail": g.get("on_fail"),
                            "method": "regex", "language": language})
        # otros tipos (json_schema, reference_check): no los evalúa este scan (igual que antes)
    return {"agent": a, "language": language, "guardrails": results,
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
