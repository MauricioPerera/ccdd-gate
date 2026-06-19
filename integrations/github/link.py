#!/usr/bin/env python3
"""link.py — trazabilidad bidireccional contrato <-> issue + sync de labels. Sin LLM.

Capa adaptadora opcional (integrations/github/). Núcleos PUROS (parse, búsqueda de contratos,
mapeo estado->labels, diff de labels) testeables sin red; los wrappers de `gh` son la capa online.

  link.py status --contract task.md            # estado del contrato (+ issue si lo referencia)
  link.py status --issue owner/repo#N [--root].# contrato(s) que referencian el issue
  link.py sync-labels --contract task.md [--post]   # refleja el estado del contrato como labels
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "runners"))
import tc_lint  # noqa: E402
import task_gate  # noqa: E402

LABEL_PREFIX = "ccdd:"
# estado del contrato -> label (acumulativo)
_STATE_LABEL = {"drafted": "ccdd:drafted", "lint_ok": "ccdd:lint-ok",
                "tests_approved": "ccdd:tests-approved", "gate_passed": "ccdd:gate-passed"}


def parse_issue_ref(s):
    """'owner/repo#N' o URL de github.com -> (owner, repo, number). ValueError si no parsea."""
    s = str(s).strip()
    if s.startswith("https://github.com/"):
        parts = s[len("https://github.com/"):].split("/")
        if len(parts) == 4 and parts[2] in ("issues", "pull"):
            return parts[0], parts[1], int(parts[3])
    if "#" in s and "/" in s.split("#")[0]:
        repo_part, num = s.split("#", 1)
        owner, repo = repo_part.split("/", 1)
        return owner, repo, int(num)
    raise ValueError(f"referencia de issue no parseable: {s}")


def normalize_issue_ref(s):
    """Forma canónica 'owner/repo#N' (para comparar URL y short)."""
    owner, repo, n = parse_issue_ref(s)
    return f"{owner}/{repo}#{n}"


def _md_matches_issue(md, target):
    """True si el task-contract `md` referencia el issue `target`. Cualquier error -> False."""
    try:
        fm, _ = tc_lint.split_front_matter(md.read_text(encoding="utf-8"))
    except Exception:
        return False
    ref = (fm or {}).get("issue")
    if not ref:
        return False
    try:
        return normalize_issue_ref(ref) == target
    except ValueError:
        return False


def contracts_referencing(issue_ref, root):
    """Rutas de task-contracts (*.md) cuyo campo `issue` resuelve al mismo issue. Función pura."""
    target = normalize_issue_ref(issue_ref)
    return [str(md) for md in sorted(Path(root).rglob("*.md")) if _md_matches_issue(md, target)]


def contract_state(task_path, run_gate=True):
    """Estado del contrato como flags: drafted/lint_ok/tests_approved/gate_passed."""
    p = Path(task_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    fm = fm or {}
    findings = tc_lint.lint(p)
    lint_ok = not any(f["level"] == "error" for f in findings)
    tests_approved = False
    tests = fm.get("tests")
    if tests and fm.get("tests_sha256"):
        tp = p.parent / tests
        if tp.exists():
            tests_approved = hashlib.sha256(tp.read_bytes()).hexdigest() == fm["tests_sha256"]
    gate_passed = False
    if run_gate and lint_ok:
        gate_passed = task_gate.gate(str(p)).get("verdict") == "PASS"
    return {"drafted": True, "lint_ok": lint_ok,
            "tests_approved": tests_approved, "gate_passed": gate_passed,
            "issue": fm.get("issue")}


def state_to_labels(state):
    """Conjunto de labels ccdd:* que corresponden al estado (los flags True)."""
    return {label for key, label in _STATE_LABEL.items() if state.get(key)}


def diff_labels(current, desired):
    """(to_add, to_remove) gestionando SOLO el prefijo ccdd:* — no pisa labels ajenas. Idempotente."""
    current = set(current)
    desired = set(desired)
    managed = {l for l in current if l.startswith(LABEL_PREFIX)}
    return sorted(desired - current), sorted(managed - desired)


# ── adaptador gh (online) ─────────────────────────────────────────────────────────────────
def _gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh falló: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def issue_state(issue_ref):
    owner, repo, n = parse_issue_ref(issue_ref)
    data = _gh_json("api", f"repos/{owner}/{repo}/issues/{n}")
    return {"number": n, "state": data.get("state"), "title": data.get("title"),
            "labels": [l["name"] for l in data.get("labels", [])]}


def sync_labels(issue_ref, desired, post=False):
    """Aplica el diff de labels al issue (idempotente, no pisa labels ajenas). Lee el estado
    actual vía gh; sin `post` devuelve el plan (dry-run, no muta)."""
    owner, repo, n = parse_issue_ref(issue_ref)
    to_add, to_remove = diff_labels(issue_state(issue_ref)["labels"], desired)
    plan = {"to_add": to_add, "to_remove": to_remove}
    if not post:
        return {"dry_run": True, **plan}
    for label in to_add:
        _gh_json("api", "--method", "POST", f"repos/{owner}/{repo}/issues/{n}/labels",
                 "-f", f"labels[]={label}")
    for label in to_remove:
        _gh_json("api", "--method", "DELETE", f"repos/{owner}/{repo}/issues/{n}/labels/{label}")
    return {"posted": True, **plan}


def _cmd_status(a):
    if a.contract:
        state = contract_state(a.contract, run_gate=not a.no_gate)
        out = {"contract": a.contract, "state": state, "labels": sorted(state_to_labels(state))}
        if state.get("issue"):
            try:
                out["issue"] = issue_state(state["issue"])
            except Exception as e:
                out["issue_error"] = str(e)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    if a.issue:
        print(json.dumps({"issue": a.issue,
                          "contracts": contracts_referencing(a.issue, a.root)},
                         ensure_ascii=False, indent=2))
        return 0
    print("status requiere --contract o --issue", file=sys.stderr)
    return 2


def _cmd_sync_labels(a):
    state = contract_state(a.contract)
    if not state.get("issue"):
        print("el contrato no tiene campo 'issue'", file=sys.stderr)
        return 2
    print(json.dumps(sync_labels(state["issue"], state_to_labels(state), post=a.post),
                     ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="link", description="Vínculo contrato<->issue + labels.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--contract")
    st.add_argument("--issue")
    st.add_argument("--root", default=".")
    st.add_argument("--no-gate", action="store_true")
    sy = sub.add_parser("sync-labels")
    sy.add_argument("--contract", required=True)
    sy.add_argument("--post", action="store_true")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    if a.cmd == "status":
        return _cmd_status(a)
    if a.cmd == "sync-labels":
        return _cmd_sync_labels(a)
    return 2


if __name__ == "__main__":
    sys.exit(main())
