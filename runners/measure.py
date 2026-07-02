#!/usr/bin/env python3
"""measure.py — harness de medición del ahorro. Corre el orquestador sobre un LOTE de
task-contracts, registra intentos/escalados/tokens (telemetría por intento que emite el
orquestador) y compara el COSTO API de NUESTRO flujo contra el flujo de moda: "loop de
modelo grande hasta completar".

Sin pretensión estadística: el número vale lo que valga el lote que le pases. Con un solo
task es el instrumento demostrado, no una medición. Pequeño local = ~0 de API por diseño.

Uso:  python measure.py task1.md [task2.md ...] --provider stub --stub a.py --stub b.py
      python measure.py tasks/*.md --provider openai --model <id> --escalate-provider ollama --escalate-model <id>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestrator as O  # noqa: E402

# Precios de referencia ($/millón de tokens). AJUSTA a tu proveedor. Pequeño local ~ 0.
PRICE = {"big_in": 15.0, "big_out": 75.0, "small_in": 0.0, "small_out": 0.0}
REVIEW_OUT_PER_LOOP = 300  # auto-juicio del modelo en el loop sin gate (out tokens por iteración)


def _cost(in_tok, out_tok, tier):
    return (in_tok * PRICE[tier + "_in"] + out_tok * PRICE[tier + "_out"]) / 1_000_000


def _is_big(label):
    return str(label).startswith("escalate")


def summarize_task(r):
    """Costo de un task bajo (a) nuestro flujo y (b) el loop de modelo grande sin gate."""
    atts = r.get("attempts") or []
    small = [a for a in atts if not _is_big(a["by"])]
    big = [a for a in atts if _is_big(a["by"])]
    si, so = sum(a.get("in_tok", 0) for a in small), sum(a.get("out_tok", 0) for a in small)
    bi, bo = sum(a.get("in_tok", 0) for a in big), sum(a.get("out_tok", 0) for a in big)
    # ¿Los tokens son medidos (usage real del provider) o estimados (len//4)?
    tok_sources = {a.get("tok_source") for a in atts if a.get("tok_source")}
    tok_kind = "measured" if tok_sources and tok_sources <= {"measured"} else (
        "estimated" if tok_sources <= {"estimated"} or not tok_sources else "mixed")
    # (a) nuestro flujo: implementación en el pequeño (~0) + grande solo en escalado; gate = 0 tokens.
    ours = _cost(si, so, "small") + _cost(bi, bo, "big")
    # (b) loop grande: MISMOS intentos pero todos en el grande, y como NO hay gate determinista,
    #     cada iteración el modelo se auto-revisa (relee el contexto + emite un juicio).
    tot_in, tot_out, loops = si + bi, so + bo, len(atts)
    big_loop = _cost(tot_in + tot_in, tot_out + loops * REVIEW_OUT_PER_LOOP, "big")
    return {"task": r["task"], "result": r["result"], "attempts": len(atts),
            "escalations": len(big), "tokens": tok_kind,
            "ours_usd": round(ours, 5), "big_loop_usd": round(big_loop, 5)}


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="measure", description="Mide ahorro: nuestro flujo vs loop de modelo grande.")
    ap.add_argument("tasks", nargs="+")
    ap.add_argument("--provider", default="stub", choices=["anthropic", "ollama", "openai", "stub"])
    ap.add_argument("--model", default="")
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument("--escalate-provider", default="anthropic", choices=["anthropic", "ollama", "openai"])
    ap.add_argument("--escalate-model", default=None)
    ap.add_argument("--escalate-attempts", type=int, default=2)
    ap.add_argument("--stub", action="append", default=[])
    return ap.parse_args(argv)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    a = parse_args(argv if argv is not None else sys.argv[1:])
    escalate = (a.escalate_provider, a.escalate_model) if a.escalate_model else None
    stub_iter = iter(a.stub)
    results = [O.implement(t, a.provider, a.model, a.max_attempts, escalate, a.escalate_attempts, stub_iter)
               for t in a.tasks]
    rows = [summarize_task(r) for r in results]
    ours, loop, passed, saving = _aggregate(rows)
    out = {"price_ref": PRICE, "per_task": rows,
           "totals": _totals(rows, ours, loop, passed, saving)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _aggregate(rows):
    """(ours_usd, big_loop_usd, passed, api_saving_pct) sobre las filas por tarea.

    api_saving_pct solo es honesto con tokens MEDIDOS (usage real del provider) y
    al menos un PASS. Con estimación len//4 (stub, o provider que no reporta usage)
    o corrida sin PASS, devolvemos None y _totals lo reporta como N/A — en vez de
    inflar un 100% falso apoyado en que el modelo pequeño cuesta $0 por definición.
    Separar 'estimado' de 'medido' es el punto: sin usage real no hay ahorro real
    que reportar, solo una proyección.
    """
    ours = sum(x["ours_usd"] for x in rows)
    loop = sum(x["big_loop_usd"] for x in rows)
    passed = sum(1 for x in rows if x["result"] == "PASS")
    measured = any(x["tokens"] == "measured" for x in rows)
    if measured and passed > 0 and loop > 0:
        saving = (1 - ours / loop) * 100
    else:
        saving = None
    return ours, loop, passed, saving


def _totals(rows, ours, loop, passed, saving):
    return {"tasks": len(rows), "passed": passed,
            "escalations": sum(x["escalations"] for x in rows),
            "gate_runs_at_0_tokens": sum(x["attempts"] for x in rows),
            "ours_usd": round(ours, 5), "big_loop_usd": round(loop, 5),
            "api_saving_pct": (round(saving, 1) if saving is not None else "N/A")}


if __name__ == "__main__":
    sys.exit(main())
