"""support_bot.py — agente de soporte de reembolsos DETERMINISTA (sin LLM), de juguete, para
ejercitar el pilar de evals Tier 1 offline. Responde anclado SOLO en el contexto provisto: lee la
ventana de reembolso del contexto (no la inventa), cita el doc por índice y se abstiene si la
consulta no es resoluble desde el contexto. Su único fin es ser el `target` del eval-contract."""
import re


def _policy_days(context):
    """(idx, dias) del primer doc del contexto que menciona una ventana de reembolso en días."""
    for i, doc in enumerate(context):
        m = re.search(r"(\d+)\s*d[ií]as", str(doc))
        if m:
            return i, int(m.group(1))
    return -1, None


def _query_days(query):
    m = re.search(r"(\d+)", query)
    return int(m.group(1)) if m else None


def answer(case_input):
    query = str(case_input.get("query", ""))
    context = list(case_input.get("context", []))
    idx, policy = _policy_days(context)
    days = _query_days(query)
    if idx == -1 or days is None:
        return {"text": "No tengo información en el contexto para responder esa consulta.",
                "citations": [], "trajectory": ["search_docs", "abstain"]}
    if days <= policy:
        text = f"Sí: estás dentro de los {policy} días para pedir el reembolso."
    else:
        text = f"No: el plazo de reembolso es de {policy} días y ya se superó."
    return {"text": text, "citations": [idx], "trajectory": ["search_docs", "compose"]}
