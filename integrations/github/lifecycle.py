#!/usr/bin/env python3
"""lifecycle.py — conecta el orquestador con el ciclo de vida de un issue de GitHub. Sin LLM aquí.

El loop del orquestador NO sabe de GitHub: recibe un callback (`on_result`) con su veredicto
determinista. Este adaptador traduce ese resultado a transiciones de label + acciones en GitHub:

  PASS      -> abre PR enlazado (Closes #N), label -> ccdd:in-review, publica veredicto (Reporter)
  ESCALATE  -> comenta el motivo, label -> ccdd:escalated
  FAIL      -> comenta y pide más descomposición, label -> ccdd:needs-split
  INVALID   -> comenta (contrato inválido), label -> ccdd:needs-split

El mapeo resultado->transición es DETERMINISTA y las transiciones de label son reversibles
(solo gestionan el conjunto de labels de ciclo de vida; no pisan otras). Sin la integración, el
orquestador corre igual en local.

Núcleos puros (decide_transition, label_transition, ready_refs) testeables sin red.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "runners"))
sys.path.insert(0, str(HERE))
import reporter  # noqa: E402

READY = "ccdd:ready"
LIFECYCLE_LABELS = {READY, "ccdd:in-review", "ccdd:escalated", "ccdd:needs-split"}

# resultado del orquestador -> (acción, label destino, motivo)
_TRANSITION = {
    "PASS": ("open_pr", "ccdd:in-review", "gate verde: PR abierto"),
    "ESCALATE": ("comment_escalate", "ccdd:escalated", "el modelo pequeño no pasó el gate dentro del budget"),
    "FAIL": ("comment_needs_split", "ccdd:needs-split", "ni el modelo grande pasó el gate: requiere más descomposición"),
    "INVALID": ("comment_invalid", "ccdd:needs-split", "el task-contract no lintea (contrato inválido)"),
}


def decide_transition(result):
    """Mapa DETERMINISTA del resultado del orquestador a {action, label, reason}. Función pura."""
    action, label, reason = _TRANSITION.get(
        result.get("result"), ("comment_invalid", "ccdd:needs-split", "resultado desconocido"))
    return {"action": action, "label": label, "reason": reason}


def label_transition(current_labels, target):
    """(to_add, to_remove) gestionando SOLO los labels de ciclo de vida — reversible, no pisa otras.
    Quita ccdd:ready y cualquier otro label de ciclo de vida distinto del destino; añade el destino."""
    current = set(current_labels)
    to_remove = sorted((current & LIFECYCLE_LABELS) - {target})
    to_add = [] if target in current else [target]
    return to_add, to_remove


def ready_refs(issues, repo):
    """Refs owner/repo#N de los issues etiquetados ccdd:ready. Función pura (testeable sin red)."""
    out = []
    for it in issues:
        labels = [label["name"] if isinstance(label, dict) else label for label in it.get("labels", [])]
        if READY in labels:
            out.append(f"{repo}#{it['number']}")
    return out


# ── adaptador gh (online) ─────────────────────────────────────────────────────────────────
def _split(issue_ref):
    repo_part, num = issue_ref.split("#", 1)
    return repo_part, int(num)


def _gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh falló: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def _gh_json(*args):
    out = _gh("api", *args)
    return json.loads(out) if out.strip() else None


def apply_labels(issue_ref, to_add, to_remove, post):
    repo, n = _split(issue_ref)
    if not post:
        return {"to_add": to_add, "to_remove": to_remove, "dry_run": True}
    for label in to_add:
        _gh_json("--method", "POST", f"repos/{repo}/issues/{n}/labels", "-f", f"labels[]={label}")
    for label in to_remove:
        _gh_json("--method", "DELETE", f"repos/{repo}/issues/{n}/labels/{label}")
    return {"to_add": to_add, "to_remove": to_remove, "posted": True}


def process(result, issue_ref, contract=None, branch=None, post=False):
    """Aplica la transición de ciclo de vida para un resultado del orquestador. Idempotente en labels."""
    decision = decide_transition(result)
    repo, n = _split(issue_ref)
    current = []
    if post:
        data = _gh_json(f"repos/{repo}/issues/{n}")
        current = [label["name"] for label in data.get("labels", [])]
    to_add, to_remove = label_transition(current, decision["label"])
    steps = {"issue": issue_ref, "decision": decision,
             "labels": apply_labels(issue_ref, to_add, to_remove, post)}

    # comentario / PR según la acción
    if decision["action"] == "open_pr":
        body = reporter.render(result.get("verdict", {"verdict": "PASS", "stage": "all"}),
                               contract=contract)
        if post:
            steps["report"] = reporter.upsert_comment(repo, n, body)
            if branch:
                title = f"ccdd: {result.get('task', 'task')}"
                steps["pr"] = _gh("pr", "create", "--repo", repo, "--head", branch,
                                  "--title", title, "--body", f"Closes #{n}\n\n{body}")
        else:
            steps["report_preview"] = body
            steps["pr_preview"] = f"PR (head={branch or 'TODO-branch'}) con 'Closes #{n}'"
    else:
        msg = f"{reporter.MARKER}\n**ccdd-gate:** {decision['reason']}\n\n" \
              f"Resultado del orquestador: `{result.get('result')}`. Label -> `{decision['label']}`."
        if post:
            steps["comment"] = reporter.upsert_comment(repo, n, msg)
        else:
            steps["comment_preview"] = msg
    return steps


def make_callback(issue_ref, contract=None, branch=None, post=False):
    """Devuelve un callback on_result(result, task_path) para pasarle al orquestador.
    El orquestador queda agnóstico de GitHub; este callback hace el puente."""
    def _cb(result, task_path):
        return process(result, issue_ref, contract=contract or task_path, branch=branch, post=post)
    return _cb


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="lifecycle", description="Transición de ciclo de vida desde un veredicto.")
    ap.add_argument("--result", required=True, help="JSON con el resultado del orquestador")
    ap.add_argument("--issue", required=True, help="owner/repo#N")
    ap.add_argument("--contract")
    ap.add_argument("--branch")
    ap.add_argument("--post", action="store_true")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    result = json.loads(Path(a.result).read_text(encoding="utf-8"))
    print(json.dumps(process(result, a.issue, contract=a.contract, branch=a.branch, post=a.post),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
