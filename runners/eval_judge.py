#!/usr/bin/env python3
"""eval_judge.py — Tier 2 (OPT-IN): juez LLM ACOTADO para lo que Tier 1 no puede capturar
deterministamente (coherencia, utilidad, tono). Es el ÚNICO módulo del pilar de evals que puede
llamar a un LLM, y su veredicto NO cuenta hasta que el juez pase judge_audit contra el golden set.

Determinismo acotado: el modelo se pinnea en el eval-contract y se llama con temperature 0. Aun
así, la salida de un proveedor puede derivar entre versiones; por eso judge_audit es obligatorio
y el CI re-corre la calibración. El provider 'stub' (offline, determinista) devuelve el
golden_judgment del caso: sirve para ejercitar la mecánica sin modelo."""
import json
import re


def judge_stub(output, case, rubric, model, api_url):
    """Determinista, offline: devuelve el golden_judgment del caso (pass/5 por defecto)."""
    g = case.get("golden_judgment") or {}
    return {"verdict": g.get("verdict", "pass"), "score": g.get("score", 5), "provider": "stub"}


def _judge_prompt(output, case, rubric):
    return ("Evalúa la respuesta del agente según la rúbrica del system. Responde SOLO JSON: "
            '{"verdict":"pass|fail","score":1-5}.\n\n'
            f"CONSULTA: {(case.get('input') or {}).get('query', '')}\n"
            f"RESPUESTA: {output.get('text', '')}")


def _parse_verdict(content):
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {"verdict": "fail", "score": 0, "error": "respuesta del juez no parseable"}
    try:
        d = json.loads(m.group(0))
        return {"verdict": d.get("verdict", "fail"), "score": int(d.get("score", 0)), "provider": "openai"}
    except Exception as e:
        return {"verdict": "fail", "score": 0, "error": str(e)}


def judge_openai(output, case, rubric, model, api_url):
    """Endpoint compatible con OpenAI (LM Studio/vLLM/Ollama), temperature 0. urllib stdlib.
    Un fallo de red/timeout/respuesta inesperada no debe tumbar la auditoría: se reporta como
    veredicto fail con el error, y judge_audit lo cuenta como desacuerdo."""
    import urllib.request
    try:
        body = json.dumps({"model": model, "temperature": 0,
                           "messages": [{"role": "system", "content": rubric},
                                        {"role": "user", "content": _judge_prompt(output, case, rubric)}]}).encode("utf-8")
        req = urllib.request.Request(f"{api_url}/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            content = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        return _parse_verdict(content)
    except Exception as e:
        return {"verdict": "fail", "score": 0, "error": f"error en la llamada al juez: {e}"}


PROVIDERS = {"stub": judge_stub, "openai": judge_openai}


def judge(output, case, rubric, provider="stub", model="", api_url=""):
    return PROVIDERS.get(provider, judge_stub)(output, case, rubric, model, api_url)
