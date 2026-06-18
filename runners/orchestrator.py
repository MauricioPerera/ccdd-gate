#!/usr/bin/env python3
"""orchestrator.py — bucle "grande planifica / pequeño implementa", honesto por gates.

Por cada task-contract:
  intento -> modelo pequeño escribe el target -> task_gate (DETERMINISTA) -> PASS/FAIL.
  FAIL: se reinyecta el detalle del gate como feedback y se reintenta (hasta --max-attempts).
  Tras agotar intentos: ESCALATE (a un modelo mayor si se da --escalate-model, si no se marca).

El gate decide, no el LLM. El modelo pequeño no puede "convencer" al gate: o la complejidad
está dentro del budget y los property-tests congelados pasan, o es FAIL. Idéntico corrida a corrida.

Providers de implementación: anthropic/ollama/openai (vía call_llm) o `stub` (offline,
secuencia de archivos .py pre-autorados — para demostrar la mecánica del loop sin modelo).

Exit: 0 todos los tasks PASS · 1 algún task quedó FAIL/ESCALATE · 2 algún contrato INVALID.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint            # noqa: E402  front-matter + parse_sig + lint
from complexity_runner import call_llm  # noqa: E402  reutiliza el cliente multi-provider

HERE = Path(__file__).resolve().parent
GATE = HERE / "task_gate.py"

CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)

SYSTEM = (
    "Eres un implementador. Recibes un task-contract PRESCRIPTIVO y devuelves EXACTAMENTE un "
    "bloque de código ```python con el MÓDULO COMPLETO del target. Sin explicaciones, sin texto "
    "fuera del bloque. Respeta la interfaz, los invariantes y el budget al pie de la letra. "
    "No inventes dependencias. Si algo es imposible dentro del budget, devuelve un bloque con un "
    "comentario `# IMPOSIBLE: <razón>` y nada más."
)


def extract_code(text):
    """Devuelve el último bloque ```python; si no hay fence, el texto crudo."""
    blocks = CODE_FENCE.findall(text or "")
    return (blocks[-1] if blocks else (text or "")).strip() + "\n"


def build_prompt(fm, body, feedback):
    """Prompt prescriptivo desde el contrato + el feedback determinista del gate (si lo hubo)."""
    head = (f"# Task: {fm.get('task')}\n"
            f"Target: {fm['target']}\n"
            f"Firma: {fm['signature']}\n"
            f"Budget: {json.dumps(fm['budget'], ensure_ascii=False)}\n"
            f"deps_allowed: {fm.get('deps_allowed', [])}\n\n")
    fb = ("" if not feedback else
          "\n\n## Veredicto del intento previo (CORREGIR ESTO)\n```json\n"
          + json.dumps(feedback, ensure_ascii=False, indent=2) + "\n```\n"
          "El gate es determinista: ajusta el código para pasarlo, no discutas el veredicto.")
    return head + body + fb


def run_gate(task_path):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, str(GATE), str(task_path)], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        verdict = json.loads(r.stdout)
    except json.JSONDecodeError:
        verdict = {"verdict": "FAIL", "stage": "gate-error", "detail": (r.stderr or r.stdout)[-400:]}
    return verdict


def next_code(provider, model, prompt, stub_iter):
    """Una salida de 'modelo' dado el prompt ya construido. Stub consume la secuencia pre-autorada."""
    if provider == "stub":
        path = next(stub_iter, None)
        return Path(path).read_text(encoding="utf-8") if path else "# IMPOSIBLE: stub agotado\n"
    return extract_code(call_llm(provider, model, SYSTEM, prompt))


def run_rounds(p, fm, body, target, provider, model, n, label, attempts, feedback, stub_iter):
    """n intentos de un mismo modelo: implementar -> gate -> reintentar con feedback.
    Devuelve (passed: bool, feedback). Anexa cada intento a `attempts`."""
    for _ in range(n):
        prompt = build_prompt(fm, body, feedback)
        code = next_code(provider, model, prompt, stub_iter)
        target.write_text(code, encoding="utf-8")
        verdict = run_gate(p)
        attempts.append({"n": len(attempts) + 1, "by": label,
                         "verdict": verdict.get("verdict"), "stage": verdict.get("stage"),
                         "in_tok": len(prompt) // 4, "out_tok": len(code) // 4})  # ~4 chars/token
        if verdict.get("verdict") == "PASS":
            return True, feedback
        feedback = verdict
    return False, feedback


def implement(task_path, provider, model, max_attempts, escalate, esc_attempts, stub_iter,
              on_result=None):
    """Loop de un task: el pequeño intenta hasta max_attempts; si no pasa, escala al grande
    que TAMBIÉN reintenta (esc_attempts) con el mismo feedback determinista.
    `escalate` es (provider, model) del modelo grande, o None para sólo marcar ESCALATE.
    `on_result` es un callback OPCIONAL (result_dict, task_path) -> ... para integraciones
    externas (p.ej. ciclo de vida de un issue de GitHub). El loop en sí NO sabe de GitHub;
    sin callback (default), corre igual en local."""
    p = Path(task_path)
    result = _implement(p, provider, model, max_attempts, escalate, esc_attempts, stub_iter)
    if on_result is not None:
        on_result(result, str(p))
    return result


def _implement(p, provider, model, max_attempts, escalate, esc_attempts, stub_iter):
    if any(f["level"] == "error" for f in tc_lint.lint(str(p))):
        return {"task": p.name, "result": "INVALID", "attempts": 0}
    fm, body = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    target = p.parent / fm["target"]
    attempts = []
    passed, feedback = run_rounds(p, fm, body, target, provider, model, max_attempts, provider, attempts, None, stub_iter)
    if passed:
        return {"task": p.name, "result": "PASS", "attempts": attempts, "by": provider}
    if not escalate:
        return {"task": p.name, "result": "ESCALATE", "attempts": attempts, "last_feedback": feedback}
    e_provider, e_model = escalate
    label = f"escalate:{e_provider}:{e_model}"
    passed, feedback = run_rounds(p, fm, body, target, e_provider, e_model, esc_attempts, label, attempts, feedback, stub_iter)
    return {"task": p.name, "result": "PASS" if passed else "FAIL", "attempts": attempts,
            "by": label, **({} if passed else {"last_feedback": feedback})}


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="orchestrator",
                                 description="Loop grande-planifica/pequeño-implementa, gateado determinista.")
    ap.add_argument("tasks", nargs="+", help="uno o más task-contracts (.md)")
    ap.add_argument("--provider", default="ollama", choices=["anthropic", "ollama", "openai", "stub"])
    ap.add_argument("--model", default="kimi-k2.7-code:cloud")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--escalate-model", default=None, help="modelo grande para el último recurso")
    ap.add_argument("--escalate-provider", default="anthropic", choices=["anthropic", "ollama", "openai"],
                    help="provider del modelo de escalado")
    ap.add_argument("--escalate-attempts", type=int, default=2, help="reintentos del modelo grande tras escalar")
    ap.add_argument("--stub", action="append", default=[],
                    help="modo stub: ruta a un .py de salida simulada; repetir por intento (en orden)")
    return ap.parse_args(argv)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    a = parse_args(argv if argv is not None else sys.argv[1:])
    stub_iter = iter(a.stub)
    escalate = (a.escalate_provider, a.escalate_model) if a.escalate_model else None
    results = [implement(t, a.provider, a.model, a.max_attempts, escalate, a.escalate_attempts, stub_iter)
               for t in a.tasks]
    summary = {"total": len(results),
               "passed": sum(1 for r in results if r["result"] == "PASS"),
               "results": results}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(r["result"] == "INVALID" for r in results):
        return 2
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
