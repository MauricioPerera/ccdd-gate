#!/usr/bin/env python3
"""ci_gate.py — driver de CI: tc_lint + task_gate sobre los contratos del PR. Sin LLM.

Pensado para correr en una GitHub Action: descubre los task-contracts afectados por el PR (los
`.md` de contrato cambiados, o aquellos cuyo `target` de código cambió), corre el veredicto
DETERMINISTA (`task_gate`: tc_lint + complejidad ≤ budget + tests congelados + firma) y:
  - falla el check (exit 1) si algún veredicto no es PASS,
  - publica un comentario combinado vía el Reporter (#13) si se le pasan --repo/--issue.

El gate es el árbitro; el LLM no entra en CI. Núcleos puros (is_contract, contracts_for_changed,
combined_report, overall_pass) testeables sin red.

  ci_gate.py task.md otro/task.md                       # corre el gate sobre esos contratos
  ci_gate.py --changed-against origin/main              # descubre los contratos del diff
  ci_gate.py --changed-against origin/main --repo o/r --issue 12 --post   # + comenta en el PR
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "runners"))
sys.path.insert(0, str(HERE))
import tc_lint  # noqa: E402
import task_gate  # noqa: E402
import reporter  # noqa: E402
import audit_composition  # noqa: E402


def is_contract(path):
    """True si el .md es un task-contract (front-matter con task+target+signature)."""
    p = Path(path)
    if p.suffix != ".md" or not p.exists():
        return False
    try:
        fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(fm) and all(k in fm for k in ("task", "target", "signature"))


def _all_contracts(root):
    return [p for p in Path(root).rglob("*.md") if is_contract(p)]


def contracts_for_changed(changed_files, root):
    """Contratos afectados: los .md de contrato cambiados + aquellos cuyo `target` cambió. Pura."""
    root = Path(root)
    changed = {str(Path(c)).replace("\\", "/") for c in changed_files}
    affected = set()
    for contract in _all_contracts(root):
        rel = str(contract.relative_to(root)).replace("\\", "/") if contract.is_relative_to(root) \
            else str(contract).replace("\\", "/")
        if rel in changed or str(contract).replace("\\", "/") in changed:
            affected.add(str(contract))
            continue
        fm, _ = tc_lint.split_front_matter(contract.read_text(encoding="utf-8"))
        target = (contract.parent / fm["target"])
        trel = str(target.relative_to(root)).replace("\\", "/") if target.is_relative_to(root) \
            else str(target).replace("\\", "/")
        if trel in changed:
            affected.add(str(contract))
    return sorted(affected)


def git_changed(base_ref):
    r = subprocess.run(["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git diff falló: {r.stderr.strip()}")
    return [l for l in r.stdout.splitlines() if l.strip()]


def run(contract_paths):
    return [{"contract": str(c), "verdict": task_gate.gate(str(c))} for c in contract_paths]


def overall_pass(results):
    return all(r["verdict"].get("verdict") == "PASS" for r in results)


def composition_note(audit):
    """Markdown de la deuda de composición (ensamblaje sin gatear). '' si ok. Pura."""
    if audit.get("ok", True):
        return ""
    items = audit.get("ungated_composition", [])
    lines = [f"### ❌ ccdd-gate: composición sin gatear ({len(items)})",
             "_Funciones que importan a otras sin un contrato `kind:group` que gatee el ensamble. "
             "El gate por-función no verifica la composición:_", ""]
    lines += [f"- `{u['contract']}` compone: {', '.join(u['composes'])}" for u in items]
    return "\n".join(lines) + "\n"


def combined_report(results):
    """Markdown combinado con un único MARKER (idempotente). Pura."""
    if not results:
        return (reporter.MARKER + "\n### ✅ ccdd-gate: sin task-contracts afectados\n\n"
                "_No hay contratos en el diff; nada que verificar._")
    ok = overall_pass(results)
    head = "✅ ccdd-gate: PASS" if ok else "❌ ccdd-gate: FAIL"
    parts = [reporter.MARKER, f"## {head} ({len(results)} contrato(s))", ""]
    for r in results:
        body = reporter.render(r["verdict"], contract=r["contract"]).replace(reporter.MARKER + "\n", "")
        parts.append(body)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="ci_gate", description="tc_lint + task_gate de los contratos del PR.")
    ap.add_argument("contracts", nargs="*", help="task-contracts explícitos")
    ap.add_argument("--changed-against", dest="base", help="ref base para descubrir cambios (p.ej. origin/main)")
    ap.add_argument("--repo", help="owner/repo (para comentar)")
    ap.add_argument("--issue", help="número de PR/issue (para comentar)")
    ap.add_argument("--post", action="store_true", help="publica el reporte vía gh")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    paths = _select_contracts(a)
    results = run(paths)
    audit = audit_composition.audit(ROOT)
    body = combined_report(results)
    note = composition_note(audit)
    if note:
        body = body.rstrip() + "\n\n" + note
    print(body)
    _maybe_post(a, body)
    return 0 if (overall_pass(results) and audit.get("ok", True)) else 1


def _select_contracts(a):
    if a.base:
        return contracts_for_changed(git_changed(a.base), ROOT)
    return [c for c in a.contracts if is_contract(c)]


def _maybe_post(a, body):
    if a.post and a.repo and a.issue:
        print(json.dumps(reporter.upsert_comment(a.repo, a.issue, body), ensure_ascii=False),
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
