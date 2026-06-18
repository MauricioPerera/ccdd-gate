#!/usr/bin/env python3
"""decompose.py — materializa task-contracts atómicos como SUB-ISSUES de GitHub. Sin LLM.

Un epic/feature NO es un task-contract (no tiene firma única ni tests congelados). El patrón:
el feature queda como issue PADRE; cada unidad atómica baja a un task-contract + su sub-issue.
Esta herramienta NO decide la descomposición (la decide el autor): solo MATERIALIZA los sub-issues
a partir de los contratos atómicos que se le pasan, y enlaza contrato<->sub-issue en ambos sentidos.

Idempotente: cada sub-issue lleva un marker `<!-- ccdd-task:<slug> -->`; re-ejecutar detecta los
existentes por marker y no duplica.

Capa adaptadora opcional (gh). Núcleos puros (build_subissue, plan, set_issue_field, find_existing)
testeables sin red.

  decompose.py --parent owner/repo#9 --contracts a.md b.md            # dry-run (plan)
  decompose.py --parent owner/repo#9 --contracts a.md b.md --post     # crea+enlaza vía gh
  decompose.py ... --non-atomic "X" "Y"   # solo reporta: se quedan como issues normales
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "runners"))
import tc_lint  # noqa: E402


def task_marker(slug):
    return f"<!-- ccdd-task:{slug} -->"


def _front_matter(task_path):
    fm, _ = tc_lint.split_front_matter(Path(task_path).read_text(encoding="utf-8"))
    return fm or {}


def build_subissue(task_path):
    """Contrato -> {slug, title, body} del sub-issue (con marker para idempotencia). Función pura."""
    fm = _front_matter(task_path)
    slug = fm.get("task") or Path(task_path).stem
    intent = fm.get("intent", "").strip().strip('"')
    title = f"[{slug}] {intent}" if intent else f"[{slug}]"
    body = "\n".join([
        task_marker(slug),
        f"**Task-contract:** `{task_path}`",
        f"**Intent:** {intent or 'TODO'}",
        "",
        "Unidad atómica (task-contract con firma única + tests congelados). "
        "El veredicto del gate se publica aquí.",
    ])
    return {"slug": slug, "title": title, "body": body, "contract": str(task_path)}


def find_existing(issues, slug):
    """Número del issue cuyo cuerpo contiene el marker del slug, o None. Pura (testeable sin red)."""
    marker = task_marker(slug)
    for it in issues:
        if marker in (it.get("body") or ""):
            return it.get("number")
    return None


def plan(contract_paths, existing_issues):
    """Plan idempotente: por contrato, create o skip (si ya existe su sub-issue por marker)."""
    out = []
    for path in contract_paths:
        sub = build_subissue(path)
        existing = find_existing(existing_issues, sub["slug"])
        out.append({**sub, "action": "skip" if existing else "create",
                    "existing_number": existing})
    return out


_ISSUE_LINE = re.compile(r"^issue:.*$", re.M)


def set_issue_field(contract_text, ref):
    """Inserta/reemplaza `issue: "ref"` en el front-matter del contrato. Función pura."""
    text = contract_text.replace("\r\n", "\n")
    m = re.match(r"^(---\n)(.*?)(\n---\n)(.*)$", text, re.S)
    if not m:
        return text  # sin front-matter: no tocar
    head, fm, close, body = m.groups()
    line = f'issue: "{ref}"'
    if _ISSUE_LINE.search(fm):
        fm = _ISSUE_LINE.sub(line, fm, count=1)
    else:
        fm = fm.rstrip("\n") + "\n" + line
    return head + fm + close + body


# ── adaptador gh (online) ─────────────────────────────────────────────────────────────────
def _gh_json(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh falló: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout) if r.stdout.strip() else None


def _parse_parent(parent):
    repo_part, num = parent.split("#", 1)
    owner, repo = repo_part.split("/", 1)
    return owner, repo, int(num)


def execute(parent, planned, post=False):
    """Crea los sub-issues 'create' y los enlaza al padre; actualiza el campo issue del contrato."""
    owner, repo, parent_n = _parse_parent(parent)
    results = []
    for item in planned:
        if item["action"] == "skip":
            ref = f"{owner}/{repo}#{item['existing_number']}"
            results.append({**item, "ref": ref})
            continue
        if not post:
            results.append({**item, "ref": None})
            continue
        created = _gh_json("api", "--method", "POST", f"repos/{owner}/{repo}/issues",
                           "-f", f"title={item['title']}", "-f", f"body={item['body']}")
        sub_n = created["number"]
        # enlazar como sub-issue del padre (API de sub-issues de GitHub)
        _gh_json("api", "--method", "POST",
                 f"repos/{owner}/{repo}/issues/{parent_n}/sub_issues",
                 "-F", f"sub_issue_id={created['id']}")
        ref = f"{owner}/{repo}#{sub_n}"
        # vínculo inverso: el contrato apunta a su sub-issue
        p = Path(item["contract"])
        p.write_text(set_issue_field(p.read_text(encoding="utf-8"), ref), encoding="utf-8")
        results.append({**item, "ref": ref, "created_number": sub_n})
    return results


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="decompose", description="Materializa contratos atómicos como sub-issues.")
    ap.add_argument("--parent", required=True, help="owner/repo#N del issue padre (feature/epic)")
    ap.add_argument("--contracts", nargs="+", required=True, help="rutas de task-contracts atómicos")
    ap.add_argument("--non-atomic", nargs="*", default=[], help="unidades NO atómicas (solo se reportan)")
    ap.add_argument("--post", action="store_true", help="crea+enlaza vía gh (si no, dry-run)")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    owner, repo, _ = _parse_parent(a.parent)
    existing = _gh_json("api", f"repos/{owner}/{repo}/issues", "--paginate",
                        "-X", "GET", "-f", "state=all") if a.post else []
    planned = plan(a.contracts, existing or [])
    results = execute(a.parent, planned, post=a.post)
    print(json.dumps({"parent": a.parent, "dry_run": not a.post,
                      "sub_issues": results,
                      "non_atomic_left_as_issues": a.non_atomic}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
