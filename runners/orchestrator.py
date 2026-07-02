#!/usr/bin/env python3
"""orchestrator.py — bucle "grande planifica / pequeño implementa", honesto por gates.

Por cada task-contract:
  intento -> modelo pequeño escribe el target -> task_gate (DETERMINISTA) -> PASS/FAIL.
  NUEVO (CEFL): Pide N candidatos en paralelo. Si alguno pasa, se queda con el de menor complejidad.
  FAIL: se reinyecta el detalle de todos los candidatos como feedback combinado y se reintenta (hasta --max-attempts).
  Tras agotar intentos: ESCALATE (a un modelo mayor si se da --escalate-model, si no se marca).

El gate decide, no el LLM. El modelo pequeño no puede "convencer" al gate: o la complejidad
está dentro del budget y los property-tests congelados pasan, o es FAIL. Idéntico corrida a corrida.

Providers de implementación: anthropic/ollama/openai (vía call_llm) o `stub` (offline,
secuencia de archivos .py pre-autorados — para demostrar la mecánica del loop sin modelo).

Exit: 0 todos los tasks PASS · 1 algún task quedó FAIL/ESCALATE · 2 algún contrato INVALID.
"""
import argparse
import concurrent.futures
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
          "\n\n## Veredicto de los intentos previos (CORREGIR ESTO)\n```json\n"
          + json.dumps(feedback, ensure_ascii=False, indent=2) + "\n```\n"
          "El gate es determinista: analiza los errores, ajusta el código para pasarlo, no discutas el veredicto.")
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


def generate_candidate(provider, model, prompt, stub_iter, temp):
    """Una salida de 'modelo' dado el prompt ya construido. Stub consume la secuencia pre-autorada."""
    if provider == "stub":
        path = next(stub_iter, None)
        return Path(path).read_text(encoding="utf-8") if path else "# IMPOSIBLE: stub agotado\n"
    # Llama a call_llm con la temperatura para asegurar variedad en la expansión CEFL
    return extract_code(call_llm(provider, model, SYSTEM, prompt, temperature=temp))


def get_complexity_score(verdict):
    """Score de complejidad si el veredicto pasó (menor es mejor).

    Suma todas las métricas que el budget limita: cyclomatic, nesting_depth,
    parameter_count y function_length (lines_max). Ignorar function_length hacía
    que el torneo pudiera premiar un candidato más largo solo porque empatara en
    las demás métricas, contradiciendo el budget completo.
    """
    m = verdict.get("metrics", {})
    return (m.get("cyclomatic", 0) + m.get("nesting_depth", 0)
            + m.get("parameter_count", 0) + m.get("function_length", 0))


def _pick_best(passed_candidates):
    """Torneo CEFL: elige el candidato de menor complejidad. Desempate determinista
    por índice de envío (menor índice gana), NO por orden de finalización — el
    ganador debe ser función solo del código, no del jitter de red."""
    return min(passed_candidates,
               key=lambda x: (get_complexity_score(x["verdict"]), x["index"]))


def _generate_candidates(provider, model, prompt, stub_iter, temp, candidates_n):
    """CEFL: genera N candidatos. Serial para stub/N=1; en paralelo (threads) si no.

    El orden de la lista devuelta es el de ENVÍO (índice 0 = primer candidato
    pedido), NO el de finalización. `as_completed` devuelve por orden de término
    (jitter de red); reordenamos por índice de envío para que el torneo posterior
    sea determinista: el ganador depende solo del código, no del tiempo de red.

    Stub: un archivo pre-autorado por intento (ver `--stub`: "repetir por intento
    en orden"). No tiene sentido la expansión paralela con stub, así que se
    consume exactamente UN stub por intento, sin importar `--candidates`. Esto es
    lo que hace que el demo del README produzca "intento 1 FAIL, intento 2 PASS".
    """
    if provider == "stub":
        return [generate_candidate(provider, model, prompt, stub_iter, temp)]
    if candidates_n == 1:
        return [generate_candidate(provider, model, prompt, stub_iter, temp)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=candidates_n) as executor:
        futures = [executor.submit(generate_candidate, provider, model, prompt, stub_iter, temp)
                   for _ in range(candidates_n)]
        # Conservar el índice de envío y reordenar por él tras recolectar.
        indexed = {id(fut): i for i, fut in enumerate(futures)}
        results = [None] * candidates_n
        for fut in concurrent.futures.as_completed(futures):
            results[indexed[id(fut)]] = fut.result()
        return results


def _evaluate_candidates(p, target, candidates_code):
    """Escribe y evalúa cada candidato aisladamente contra el gate determinista.

    Devuelve la lista evaluada con el índice de envío de cada candidato (su
    posición en `candidates_code`), que se usa como desempate determinista en
    el torneo.
    """
    evaluated = []
    for idx, code in enumerate(candidates_code):
        target.write_text(code, encoding="utf-8")
        verdict = run_gate(p)
        evaluated.append({"index": idx, "code": code, "verdict": verdict})
    return evaluated


def _fail_feedback(evaluated, candidates_n):
    """Feedback combinado masivo cuando ningún candidato pasó."""
    return {
        "verdict": "FAIL_ALL_CANDIDATES",
        "message": f"Se generaron {candidates_n} candidatos paralelos y TODOS fallaron. Analiza los errores y proporciona una solución unificada que corrija los defectos.",
        "candidates_evaluations": [{"candidate_code": e["code"], "gate_error": e["verdict"]} for e in evaluated],
    }


def run_rounds(p, fm, body, target, provider, model, max_attempts, label, attempts, feedback, stub_iter, candidates_n, temp):
    """max_attempts intentos. En cada intento, pide `candidates_n` soluciones en paralelo.
    Si alguna pasa, elige la de menor complejidad (CEFL). Si ninguna pasa, retroalimenta los N fallos.

    El torneo es determinista: ante empate de score gana el candidato de menor
    índice de envío (no el que terminó primero). Los tokens se reportan como
    `*_tok_est` (estimación len//4) salvo que el provider aporte uso real.
    """
    for attempt_num in range(max_attempts):
        prompt = build_prompt(fm, body, feedback)

        candidates_code = _generate_candidates(provider, model, prompt, stub_iter, temp, candidates_n)
        n_candidates = len(candidates_code)
        original_target_code = target.read_text(encoding="utf-8") if target.exists() else ""
        evaluated = _evaluate_candidates(p, target, candidates_code)

        passed_candidates = [e for e in evaluated if e["verdict"].get("verdict") == "PASS"]
        if passed_candidates:
            # Torneo: menor score gana; desempate determinista por índice de envío
            # (NO por orden de finalización, que depende del jitter de red).
            best = _pick_best(passed_candidates)
            target.write_text(best["code"], encoding="utf-8")
            in_tok, out_tok, tok_source = _token_usage(prompt, best["code"], best["verdict"])
            attempts.append({"n": attempt_num + 1, "by": label,
                             "verdict": "PASS", "stage": best["verdict"].get("stage"),
                             "cefl_candidates": n_candidates,
                             "in_tok": in_tok, "out_tok": out_tok,
                             "tok_source": tok_source,
                             "best_candidate_index": best["index"],
                             "best_complexity_score": get_complexity_score(best["verdict"])})
            return True, None

        # Ninguno pasó: restaurar código original y preparar feedback combinado
        target.write_text(original_target_code, encoding="utf-8")
        attempts.append({"n": attempt_num + 1, "by": label,
                         "verdict": "FAIL", "stage": "all_candidates_failed",
                         "cefl_candidates": n_candidates})
        feedback = _fail_feedback(evaluated, n_candidates)

    return False, feedback


def _token_usage(prompt, code, verdict):
    """Tokens consumidos por el intento. Usa el usage real del provider si está en el
    veredicto; si no, estima len//4 y lo etiqueta como 'estimado'."""
    usage = (verdict or {}).get("usage") or {}
    if usage.get("in_tok") is not None and usage.get("out_tok") is not None:
        return usage["in_tok"], usage["out_tok"], "measured"
    return len(prompt) // 4, len(code) // 4, "estimated"


def implement(task_path, provider, model, max_attempts, escalate, esc_attempts, stub_iter,
              candidates_n=1, temp=0.7, on_result=None):
    p = Path(task_path)
    result = _implement(p, provider, model, max_attempts, escalate, esc_attempts, stub_iter, candidates_n, temp)
    if on_result is not None:
        on_result(result, str(p))
    return result


def _implement(p, provider, model, max_attempts, escalate, esc_attempts, stub_iter, candidates_n, temp):
    if any(f["level"] == "error" for f in tc_lint.lint(str(p))):
        return {"task": p.name, "result": "INVALID", "attempts": 0}
    fm, body = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    target = p.parent / fm["target"]
    attempts = []
    
    passed, feedback = run_rounds(p, fm, body, target, provider, model, max_attempts, provider, attempts, None, stub_iter, candidates_n, temp)
    if passed:
        return {"task": p.name, "result": "PASS", "attempts": attempts, "by": provider}
        
    if not escalate:
        return {"task": p.name, "result": "ESCALATE", "attempts": attempts, "last_feedback": feedback}
        
    e_provider, e_model = escalate
    label = f"escalate:{e_provider}:{e_model}"
    passed, feedback = run_rounds(p, fm, body, target, e_provider, e_model, esc_attempts, label, attempts, feedback, stub_iter, candidates_n, temp)
    
    return {"task": p.name, "result": "PASS" if passed else "FAIL", "attempts": attempts,
            "by": label, **({} if passed else {"last_feedback": feedback})}


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="orchestrator",
                                 description="Loop grande-planifica/pequeño-implementa, gateado determinista con CEFL paralelo.")
    ap.add_argument("tasks", nargs="+", help="uno o más task-contracts (.md)")
    ap.add_argument("--provider", default="ollama", choices=["anthropic", "ollama", "openai", "stub"])
    ap.add_argument("--model", default="kimi-k2.7-code:cloud")
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--escalate-model", default=None, help="modelo grande para el último recurso")
    ap.add_argument("--escalate-provider", default="anthropic", choices=["anthropic", "ollama", "openai"],
                    help="provider del modelo de escalado")
    ap.add_argument("--escalate-attempts", type=int, default=2, help="reintentos del modelo grande tras escalar")
    ap.add_argument("--candidates", type=int, default=3, help="Número de candidatos a generar en paralelo (estilo CEFL)")
    ap.add_argument("--temperature", type=float, default=0.7, help="Temperatura para generar variaciones de código")
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
    
    results = [implement(t, a.provider, a.model, a.max_attempts, escalate, a.escalate_attempts, stub_iter, a.candidates, a.temperature)
               for t in a.tasks]

    summary = _summary(results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return _exit_code(results, summary)


def _summary(results):
    return {"total": len(results),
            "passed": sum(1 for r in results if r["result"] == "PASS"),
            "results": results}


def _exit_code(results, summary):
    if any(r["result"] == "INVALID" for r in results):
        return 2
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
