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
    {
        "name": "request_human_attestation",
        "description": "Herramienta que el agente invoca cuando choca de frente contra un umbral estructural (Complexity Gate) "
                       "que NO puede ser simplificado por reglas de negocio. Esta herramienta calcula un Hash Semántico del "
                       "código y emite una petición oficial de firma. Un arquitecto humano revisará el código y, si está "
                       "de acuerdo, firmará la excepción con su clave Ed25519, desbloqueando el gate.",
        "inputSchema": {"type": "object", "required": ["code", "reason"], "properties": {
            "code": {"type": "string", "description": "El código fuente de la función o módulo problemático."},
            "reason": {"type": "string", "description": "Justificación técnica clara de por qué este código NECESITA "
                       "violar el umbral actual (ej. 'Requiere anidamiento nivel 5 por el switch case de negocio X')."},
            "agent": {"type": "string", "enum": sorted(AGENTS), "description": "El agente contra el que corría (default complexity-agent)."},
            "filename": {"type": "string", "description": "Nombre de archivo (opcional)."}
        }},
    },
    {
        "name": "run_ephemeral_agent",
        "description": "Delega un Task Contract a un LLM local (Small Executor). Lee el contrato, envía el código al LLM, y entra en un bucle de reflexión (max 3 veces) validando con task_gate.py hasta que el código pase el gate determinista. Retorna el resultado final y el número de intentos.",
        "inputSchema": {"type": "object", "required": ["task_path"], "properties": {
            "task_path": {"type": "string", "description": "Ruta relativa o absoluta al archivo del Task Contract (.md)."},
            "model": {"type": "string", "description": "Nombre del modelo a usar (default: gemma-4-12b-coder)."},
            "api_url": {"type": "string", "description": "URL base de la API OpenAI-compatible (default: http://localhost:1234/v1)."}
        }},
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
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get(language, [])


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
    except (KeyError, SyntaxError, ValueError):
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
            # Respeta el subdirectorio de `tests:` creando los dirs intermedios; nunca escribe
            # fuera del tempdir (una ruta con `..`/absoluta cae al basename dentro del tempdir).
            base = Path(d)
            tp = base / tests_name
            try:
                tp.resolve().relative_to(base.resolve())
            except ValueError:
                tp = base / Path(tests_name).name
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(args["test_code"], encoding="utf-8")
        findings = tc_lint.lint(task)
    errors = sum(1 for f in findings if f["level"] == "error")
    return {"ok": errors == 0, "errors": errors,
            "warnings": len(findings) - errors, "findings": findings,
            "tests_provided": "test_code" in args}


def request_human_attestation(args):
    code = args.get("code", "")
    reason = args.get("reason", "")
    agent = args.get("agent", DEFAULT_AGENT)
    fname = args.get("filename", "snippet.py")
    if not code or not reason:
        return {"error": "Falta el código o la justificación (reason)."}

    try:
        import semantic_hash
        ext = Path(fname).suffix or ".py"
        h = semantic_hash.get_semantic_hash(code, ext)
    except Exception as e:
        import hashlib
        h = hashlib.sha256(code.encode("utf-8")).hexdigest()

    out_dir = CONTRACTS / agent / "pending_attestations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{h}.json"

    data = {
        "hash": h,
        "filename": fname,
        "reason": reason,
        "code": code
    }
    out_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "Atestación solicitada",
        "hash": h,
        "message": f"Se ha registrado la petición oficial para el hash {h}. Avisa al arquitecto humano que debe revisar esta petición para desbloquear el gate."
    }

class _BraceScanner:
    """Recorre `source` desde la llave de apertura hasta su cierre balanceado,
    ignorando llaves dentro de strings y comentarios (// y /* */). Cada modo
    (comentario de línea, comentario de bloque, string, código) tiene su propio
    consumidor pequeño: mantiene la complejidad ciclomática de cada paso baja."""

    def __init__(self, source, start):
        self.src = source
        self.i = start
        self.depth = 0
        self.string_char = None
        self.escape = False
        self.in_line_comment = False
        self.in_block_comment = False

    def _peek(self):
        return self.src[self.i + 1] if self.i + 1 < len(self.src) else ""

    def _consume_line_comment(self, c):
        if c == "\n":
            self.in_line_comment = False
        self.i += 1

    def _consume_block_comment(self, c):
        if c == "*" and self._peek() == "/":
            self.in_block_comment = False
            self.i += 2
        else:
            self.i += 1

    def _consume_string(self, c):
        if self.escape:
            self.escape = False
        elif c == "\\":
            self.escape = True
        elif c == self.string_char:
            self.string_char = None
        self.i += 1

    def _consume_code(self, c):
        """Devuelve el índice de fin (exclusivo) si se cierra el bloque, si no None.
        Guard clauses secuenciales (no if/elif) para mantener el anidamiento plano."""
        nxt = self._peek()
        if c == "/" and nxt == "/":
            self.in_line_comment = True
            self.i += 2
            return None
        if c == "/" and nxt == "*":
            self.in_block_comment = True
            self.i += 2
            return None
        if c in ("'", '"', "`"):
            self.string_char = c
            self.i += 1
            return None
        if c == "{":
            self.depth += 1
            self.i += 1
            return None
        if c == "}":
            self.depth -= 1
            self.i += 1
            return self.i if self.depth == 0 else None
        self.i += 1
        return None

    def _active_consumer(self):
        """Selecciona el consumidor según el modo actual (sin anidar ramas)."""
        if self.in_line_comment:
            return self._consume_line_comment
        if self.in_block_comment:
            return self._consume_block_comment
        if self.string_char is not None:
            return self._consume_string
        return self._consume_code

    def find_end(self):
        """Índice de fin (exclusivo) del bloque, o -1 si no balancea."""
        while self.i < len(self.src):
            end = self._active_consumer()(self.src[self.i])
            if end is not None:
                return end
        return -1


def _find_block_start(source, signature):
    """(idx_firma, idx_llave_apertura). (-1, -1) si no se encuentra."""
    idx = source.find(signature)
    if idx == -1:
        return -1, -1
    if "{" in signature:
        return idx, idx + signature.rfind("{")
    return idx, source.find("{", idx + len(signature))


def extract_brace_block(source, signature):
    idx, start_brace = _find_block_start(source, signature)
    if idx == -1 or start_brace == -1:
        return None, -1, -1
    end = _BraceScanner(source, start_brace).find_end()
    if end == -1:
        return None, -1, -1
    return source[idx:end], idx, end

def _prepare_ephemeral_task(args):
    """Carga el task-contract y el target. Devuelve (ctx, None) o (None, error_dict)."""
    task_path = args.get("task_path")
    tp = Path(task_path)
    if not tp.exists():
        return None, {"status": "FAIL", "reason": f"Task file no encontrado: {task_path}"}
    try:
        task_content = tp.read_text(encoding="utf-8")
        fm, _body = tc_lint.split_front_matter(task_content)
        target = tp.parent / fm["target"]
        if not target.exists():
            return None, {"status": "FAIL", "reason": f"Target no encontrado: {target}"}
        original_source = target.read_text(encoding="utf-8")
    except Exception as e:
        return None, {"status": "FAIL", "reason": f"Error parseando: {e}"}
    return {
        "tp": tp,
        "model": args.get("model", "gemma-4-12b-coder"),
        "api_url": args.get("api_url", "http://localhost:1234/v1"),
        "task_content": task_content,
        "target": target,
        "original_source": original_source,
        "signature": fm.get("signature", ""),
    }, None


def _build_ephemeral_prompts(ctx):
    """Prompts iniciales + bloque a reemplazar. Devuelve (sys, user, block, start, end)."""
    signature = ctx["signature"]
    target = ctx["target"]
    original_source = ctx["original_source"]
    task_content = ctx["task_content"]

    target_block, start_idx, end_idx = None, -1, -1
    # Intento de compactación (Tree-shaking estático vía firmas)
    if signature and target.suffix in [".js", ".ts", ".java", ".c", ".cpp", ".cs"]:
        target_block, start_idx, end_idx = extract_brace_block(original_source, signature)

    if target_block:
        sys_prompt = "Eres un Small Executor experto en refactorización. Se te dará UNA FUNCIÓN aislada. Devuelve la función refactorizada completa y SI LO NECESITAS, incluye funciones auxiliares ANTES o DESPUÉS de la principal. REGLA CRÍTICA: DEBES MANTENER LA FIRMA DE LA FUNCIÓN ORIGINAL EXACTAMENTE INTACTA."
        user_prompt = f"### TASK CONTRACT:\n{task_content}\n\n### FIRMA ORIGINAL REQUERIDA:\n{signature}\n\n### FUNCIÓN AISLADA (Compactada):\n```\n{target_block}\n```"
    else:
        sys_prompt = "Eres un Small Executor experto en refactorización orientada a métricas de complejidad ciclomática."
        user_prompt = f"### TASK CONTRACT:\\n{task_content}\\n\\n### CODIGO FUENTE COMPLETO:\\n```\\n{original_source}\\n```\\n\\nDevuelve TODO el archivo refactorizado dentro de un bloque markdown de código (```)."
    return sys_prompt, user_prompt, target_block, start_idx, end_idx


def _sse_delta_content(data_str):
    """Extrae delta.content de una línea SSE de chat completions ('' si no aplica)."""
    try:
        delta = json.loads(data_str)["choices"][0].get("delta", {})
    except json.JSONDecodeError:
        return ""
    return delta.get("content", "")


def _read_sse_content(response):
    """Acumula el content del stream SSE hasta [DONE]. Devuelve (content, timed_out)."""
    import socket
    content = ""
    try:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            data_str = line[6:].decode("utf-8").strip()
            if data_str == "[DONE]":
                break
            content += _sse_delta_content(data_str)
    except socket.timeout:
        return content, True
    return content, False


def _stream_completion(api_url, model, messages):
    """Llama al LLM en streaming. Devuelve (partial_content, timed_out, error_dict)."""
    import urllib.request
    import socket

    data = json.dumps({"model": model, "messages": messages, "temperature": 0.2,
                       "max_tokens": 8000, "stream": True}).encode("utf-8")
    req = urllib.request.Request(f"{api_url}/chat/completions", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            content, timed_out = _read_sse_content(response)
            return content, timed_out, None
    except socket.timeout:
        return "", True, None
    except Exception as e:
        return "", False, {"reason": f"Error conectando al LLM: {e}"}


def _extract_new_code(messages, partial_content):
    """Une las continuaciones previas y extrae el bloque de código markdown."""
    full_answer = "".join(m["content"] for m in messages if m["role"] == "assistant")
    full_answer += partial_content
    code_match = re.search(r"```[a-zA-Z]*\n(.*?)```", full_answer, re.DOTALL)
    new_code = code_match.group(1).strip() if code_match else full_answer.strip()
    return new_code, full_answer


def _apply_new_code(target, new_code, target_block, original_source, start_idx, end_idx):
    if target_block:
        merged = original_source[:start_idx] + new_code + original_source[end_idx:]
        target.write_text(merged, encoding="utf-8")
    else:
        target.write_text(new_code, encoding="utf-8")


def _complexity_feedback(gate_json, signature):
    """Feedback específico de gate2-complexity, o '' si no aplica."""
    over_budget = gate_json.get("over_budget", [])
    actual = limit = cyclo_delta = 0
    for ob in over_budget:
        if "cyclomatic=" in ob and "cyclomatic_max=" in ob:
            parts = re.findall(r"\d+", ob)
            if len(parts) >= 2:
                actual, limit = int(parts[0]), int(parts[1])
                cyclo_delta = actual - limit
    if cyclo_delta <= 0:
        return ""
    return (
        "[!] ÉXITO SINTÁCTICO: ¡Tu código superó las pruebas y es válido!\n\n"
        f"[!] ALERTA MATEMÁTICA: Sin embargo, la complejidad ciclomática actual es {actual}, y el MÁXIMO ESTRICTO permitido es {limit}. ¡ESTÁS EXCEDIDO POR {cyclo_delta} PUNTOS!\n\n"
        "[!] HEURÍSTICA OBLIGATORIA: Para reducir la complejidad drásticamente, NO intentes reescribir todo en la misma función con retornos tempranos. DEBES EXTRAER bloques lógicos (validaciones, iteraciones, branches complejos) a NUEVAS sub-funciones auxiliares privadas que sean llamadas desde la función principal. Escribe estas sub-funciones en el mismo bloque markdown.\n"
        f"[!] REGLA CRÍTICA: La función principal DEBE mantener exactamente esta firma: `{signature}`. No la borres, no la renombres, y no la conviertas en arrow function si no lo era. MANTÉN LOS TESTS PASANDO.\n\n"
    )


def _stage_feedback(gate_json, signature):
    """Feedback específico según la etapa del gate que falló."""
    stage = gate_json.get("stage")
    if stage == "gate2-complexity":
        return _complexity_feedback(gate_json, signature)
    if stage == "gate1-tests":
        error_output = gate_json.get("output", "Error desconocido en los tests.")
        return (f"[!] ALERTA SINTÁCTICA / TESTS: La ejecución del código falló. Revisa el siguiente error que lanzó el validador (puede ser un error de sintaxis o un test fallido):\n\n```\n{error_output}\n```\n\n"
                "[!] INSTRUCCIÓN: Corrige EXACTAMENTE este error lógico o de sintaxis. Asegúrate de que el código sea Javascript/TypeScript válido y que cumpla la firma requerida.\n\n")
    return ""


def _build_feedback(output_str, signature):
    """Construye el prompt de feedback cuantitativo a partir del output del gate."""
    feedback = f"El validador matemático rechazó tu código. Output original:\n{output_str}\n\n"
    try:
        match = re.search(r'(\{.*"verdict":.*"FAIL".*\})', output_str, re.DOTALL)
        if match:
            feedback += _stage_feedback(json.loads(match.group(1)), signature)
    except Exception:
        pass
    feedback += "Por favor genera el código DESDE CERO aplicando estas correcciones. NO repitas el código roto."
    return feedback


def run_ephemeral_agent(args):
    import subprocess

    ctx, error = _prepare_ephemeral_task(args)
    if error:
        return error

    sys_prompt, user_prompt, target_block, start_idx, end_idx = _build_ephemeral_prompts(ctx)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

    proc = None
    max_iterations = 3
    gate_script = HERE / "task_gate.py"
    for i in range(max_iterations):
        partial_content, timed_out, error = _stream_completion(ctx["api_url"], ctx["model"], messages)
        if error:
            return {"status": "FAIL", "iteration": i + 1, **error}

        if timed_out and partial_content:
            messages.append({"role": "assistant", "content": partial_content})
            messages.append({"role": "user", "content": "Se alcanzó el timeout. Continúa generando el código EXACTAMENTE donde te quedaste (no repitas el inicio, solo escupe la continuación)."})
            continue  # consume una iteración del límite lógico del Gate

        new_code, full_answer = _extract_new_code(messages, partial_content)
        print(f"\n=== LLM OUTPUT ITERATION {i+1} ===\n{full_answer}\n================================\n", file=sys.stderr)
        _apply_new_code(ctx["target"], new_code, target_block, ctx["original_source"], start_idx, end_idx)

        proc = subprocess.run([sys.executable, str(gate_script), str(ctx["tp"])],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0:
            return {"status": "PASS", "iterations": i + 1, "gate_output": proc.stdout}

        feedback_prompt = _build_feedback(proc.stdout or proc.stderr, ctx["signature"])
        # Stateless feedback: no incluimos full_answer para que el LLM no se contamine con su propia basura
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt + "\n\n### FEEDBACK DEL INTENTO ANTERIOR:\n" + feedback_prompt},
        ]

    # Restaurar si falló
    ctx["target"].write_text(ctx["original_source"], encoding="utf-8")
    return {"status": "FAIL", "iterations": max_iterations, "reason": "Max iteraciones",
            "last_gate": (proc.stdout or proc.stderr) if proc else ""}


DISPATCH = {"measure_complexity": measure_complexity,
            "complexity_rubric": complexity_rubric,
            "scan_guardrails": scan_guardrails,
            "lint_task_contract": lint_task_contract,
            "request_human_attestation": request_human_attestation,
            "run_ephemeral_agent": run_ephemeral_agent}


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
