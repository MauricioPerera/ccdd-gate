"""pre_complexity_helpers.py — helpers de transformación de datos para el runner.
Sin lógica de negocio: extracción del bloque JSON de la respuesta y construcción del
reporte de salida. El runner orquesta; aquí solo se transforman datos."""
import json

_SEVERITY_KEYS = {"CRÍTICA": "critical", "ALTA": "high", "MEDIA": "medium", "INFO": "info"}


def split_text_and_json(raw):
    """Separa el texto libre del bloque ```json final de la respuesta del LLM.
    Devuelve (texto_libre, dict|None). No usa regex: localiza el fence por string."""
    fence = raw.rfind("```json")
    if fence == -1:
        return raw.strip(), None
    end = raw.find("```", fence + 7)
    block = raw[fence + 7: end if end != -1 else len(raw)]
    free = (raw[:fence] + (raw[end + 3:] if end != -1 else "")).strip()
    try:
        return free, json.loads(block)
    except json.JSONDecodeError:
        return raw.strip(), None


_AUTO = {
    "compound-requirement": ("MEDIA", "lingüística", "ciclomática",
        "requisito compuesto detectado (múltiples conectores 'y además' en una unidad).",
        "dividir el requisito compuesto en unidades de responsabilidad única."),
    "deep-nesting": ("ALTA", "estructural", "cognitiva",
        "anidamiento profundo (≥4 niveles de indentación) detectado en el código.",
        "extraer los bloques internos a funciones o aplicar guard clauses para aplanar."),
}


def auto_signal(guardrail_id):
    """Señal automática (sin inferencia) por un guardrail de reroute disparado."""
    sev, typ, pred, desc, fix = _AUTO.get(
        guardrail_id, ("MEDIA", "estructural", "cognitiva",
                       f"guardrail '{guardrail_id}' disparó (detección determinista).", None))
    return {
        "severity": sev,
        "location": "detección determinista (guardrail)",
        "description": desc,
        "type": typ,
        "prediction": pred,
        "classification": "ACCIDENTAL",
        "redesign_suggestion": fix,
    }


def build_report(contract_name, contract_version, input_file, timestamp, llm, signals, guardrails_triggered, domain_available):
    """Construye analysis_report.json. `llm` es el dict parseado del bloque (o None);
    `signals` es la lista final (LLM + automáticas)."""
    counts = {"critical": 0, "high": 0, "medium": 0, "info": 0}
    for s in signals:
        k = _SEVERITY_KEYS.get(str(s.get("severity", "")).upper())
        if k:
            counts[k] += 1
    summary_llm = (llm or {}).get("summary", {})
    critical = counts["critical"]
    return {
        "contract": contract_name,
        "contract_version": contract_version,
        "timestamp": timestamp,
        "input_file": input_file,
        "signals": signals,
        "summary": {
            "total": len(signals),
            "critical": critical,
            "high": counts["high"],
            "medium": counts["medium"],
            "info": counts["info"],
            "dominant_complexity": summary_llm.get("dominant_complexity", "indeterminada"),
            "recommendation": summary_llm.get(
                "recommendation",
                "REDISEÑAR ANTES DE IMPLEMENTAR" if critical else "CONTINUAR CON MONITOREO"),
            "estimated_cost_of_ignoring": summary_llm.get(
                "estimated_cost_of_ignoring", "ALTO" if critical else "BAJO"),
        },
        "guardrails_triggered": guardrails_triggered,
        "domain_context_available": domain_available,
        "verdict": "FAIL" if critical else "PASS",
    }
