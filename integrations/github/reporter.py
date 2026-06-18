#!/usr/bin/env python3
"""reporter.py — veredicto DETERMINISTA del gate como comentario legible (issue/PR). Sin LLM.

Toma la salida JSON de `task_gate`/`complexity_gate` (el árbitro determinista) y produce un
comentario Markdown estructurado: PASS/FAIL, métricas por función vs budget, motivo del fallo,
firma de tests y enlace al contrato. El `render` es función PURA (mismo JSON -> mismo Markdown),
sin timestamps ni nada no determinista, para que la actualización sea idempotente.

Capa adaptadora opcional (integrations/github/): el core del gate sigue emitiendo solo JSON.
- Offline:  genera el Markdown (no toca la red).
- Online:   publica/actualiza un comentario "marcado" (HTML marker) vía `gh` — no spamea.

Uso:
  python reporter.py verdict.json                         # imprime el Markdown (offline)
  python reporter.py verdict.json --repo o/r --issue 12   # imprime lo que publicaría (dry-run)
  python reporter.py verdict.json --repo o/r --issue 12 --post   # publica/actualiza vía gh
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

MARKER = "<!-- ccdd-gate:report -->"
_HEADER = {"PASS": "✅ ccdd-gate: PASS", "FAIL": "❌ ccdd-gate: FAIL",
           "INVALID": "⚠️ ccdd-gate: INVALID (contrato)"}
# métrica -> clave de budget (espejo de task_gate.BUDGET_KEY)
_BUDGET_KEY = {"cyclomatic": "cyclomatic_max", "nesting_depth": "nesting_max",
               "parameter_count": "params_max", "function_length": "lines_max"}


def _metrics_table(metrics, budget):
    rows = ["| métrica | valor | budget |", "|---|---|---|"]
    for metric, key in _BUDGET_KEY.items():
        if metric in metrics:
            cap = budget.get(key, "—") if isinstance(budget, dict) else "—"
            rows.append(f"| {metric} | {metrics[metric]} | {cap} |")
    return "\n".join(rows)


def render(verdict, contract=None, target=None):
    """JSON de veredicto -> Markdown determinista (con marker oculto para updates idempotentes)."""
    v = verdict.get("verdict", "FAIL")
    lines = [MARKER, f"### {_HEADER.get(v, '❓ ccdd-gate')}", ""]
    fn = verdict.get("function")
    if fn:
        lines.append(f"**Función:** `{fn}`  ")
    lines.append(f"**Etapa:** `{verdict.get('stage', '—')}`")
    lines.append("")
    if v == "PASS" and isinstance(verdict.get("metrics"), dict):
        lines.append(_metrics_table(verdict["metrics"], verdict.get("budget") or {}))
    over = verdict.get("over_budget")
    if over:
        lines.append("**Métricas sobre budget:**")
        lines += [f"- `{x}`" for x in over]
    detail = verdict.get("detail")
    if detail:
        lines.append(f"**Motivo:** {detail}")
    out = verdict.get("output")
    if out:
        lines += ["", "<details><summary>salida de los tests</summary>", "",
                  "```", out.strip()[-1500:], "```", "</details>"]
    if contract:
        lines += ["", f"Contrato: `{contract}`"]
    lines += ["", "_Veredicto determinista (sin LLM); este comentario se actualiza en cada corrida._"]
    return "\n".join(lines)


# ── adaptador GitHub (opcional, vía gh CLI) ───────────────────────────────────────────────
def find_marked_comment(comments, marker=MARKER):
    """ID del primer comentario que contiene el marker, o None. Función pura (testeable sin red)."""
    for c in comments:
        if marker in (c.get("body") or ""):
            return c.get("id")
    return None


def _gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh falló: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def upsert_comment(repo, issue, body, marker=MARKER):
    """Crea o ACTUALIZA (por marker) el comentario del gate. Idempotente: no duplica."""
    comments = _gh_json("api", f"repos/{repo}/issues/{issue}/comments", "--paginate") or []
    cid = find_marked_comment(comments, marker)
    if cid is not None:
        _gh_json("api", "--method", "PATCH", f"repos/{repo}/issues/comments/{cid}",
                 "-f", f"body={body}")
        return {"action": "updated", "comment_id": cid}
    _gh_json("api", "--method", "POST", f"repos/{repo}/issues/{issue}/comments",
             "-f", f"body={body}")
    return {"action": "created"}


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="reporter", description="Veredicto del gate como comentario.")
    ap.add_argument("verdict", help="archivo JSON con la salida de task_gate/complexity_gate")
    ap.add_argument("--contract", help="ruta/enlace del task-contract (opcional)")
    ap.add_argument("--repo", help="owner/repo (para publicar)")
    ap.add_argument("--issue", help="número de issue/PR (para publicar)")
    ap.add_argument("--post", action="store_true", help="publica/actualiza vía gh (si no, dry-run)")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    verdict = json.loads(Path(a.verdict).read_text(encoding="utf-8"))
    body = render(verdict, contract=a.contract)
    if a.post:
        if not (a.repo and a.issue):
            print("--post requiere --repo y --issue", file=sys.stderr)
            return 2
        print(json.dumps(upsert_comment(a.repo, a.issue, body), ensure_ascii=False))
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
