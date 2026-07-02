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
import audit_annotations  # noqa: E402
import mutation_audit  # noqa: E402


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
    """Markdown de la deuda de COMPOSICIÓN sin verificar (el test del composer mockea o falta). '' si
    ok (las composiciones cuyo test ejercita los hijos reales son deuda de forma, no se reportan)."""
    if audit.get("ok", True):
        return ""
    items = audit.get("behavior_unverified", audit.get("ungated_composition", []))
    lines = [f"### ❌ ccdd-gate: composición sin verificar ({len(items)})",
             "_Funciones que componen a otras pero cuyo test NO ejercita los hijos reales "
             "(mockea o falta) y no hay un `kind:group` que gatee el ensamble:_", ""]
    lines += [f"- `{u['contract']}` compone: {', '.join(u['composes'])}" for u in items]
    return "\n".join(lines) + "\n"


def annotations_note(ann):
    """Markdown de nombres de anotación sin importar (project-wide). '' si ok. Pura."""
    if ann.get("ok", True):
        return ""
    fails = ann.get("failures", [])
    lines = [f"### ❌ ccdd-gate: anotaciones sin resolver ({len(fails)})",
             "_Targets con nombres usados en anotaciones sin importar/definir (rompen en <Py3.14):_", ""]
    lines += [f"- `{f['target']}`: {f['detail'].split(':')[-1].strip()}" for f in fails]
    return "\n".join(lines) + "\n"


def mutation_survivors(contract_paths):
    """Corre mutation_audit SOLO en los contratos afectados (acotado). Devuelve lista de
    {contract, survived} con mutantes sobrevivientes. Pura respecto del estado (restaura el target)."""
    out = []
    for c in contract_paths:
        res = mutation_audit.audit(str(c))
        if res.get("survived"):
            out.append({"contract": str(c), "survived": res["survived"]})
    return out


def mutation_note(survivors):
    """Markdown de mutantes sobrevivientes (oráculo débil) en los contratos del PR. '' si ninguno."""
    if not survivors:
        return ""
    lines = [f"### ❌ ccdd-gate: oráculo débil — mutantes sobrevivientes ({len(survivors)} contrato/s)",
             "_El test no caza estas mutaciones del target (oráculo no pinea esa lógica):_", ""]
    lines += [f"- `{s['contract']}`: {', '.join(s['survived'])}" for s in survivors]
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
    audit = audit_composition.audit(ROOT)          # composición: project-wide
    ann = audit_annotations.audit(ROOT)            # anotaciones: project-wide (barato)
    survivors = mutation_survivors(paths)          # oráculo: SOLO los contratos del PR (acotado)
    body = combined_report(results)
    for extra in (composition_note(audit), annotations_note(ann), mutation_note(survivors)):
        if extra:
            body = body.rstrip() + "\n\n" + extra
    print(body)
    # El posting (comentar en el PR) es best-effort: un fallo de `gh` (p.ej. token
    # read-only en PRs de fork) NO debe pisar el veredicto del gate. Se loguea a stderr
    # y el exit code sigue al veredicto, no a la capacidad de comentar.
    try:
        _maybe_post(a, body)
    except Exception as e:
        print(f"[ci-gate] posting falló (no afecta el veredicto del gate): {e}", file=sys.stderr)
    ok = overall_pass(results) and audit.get("ok", True) and ann.get("ok", True) and not survivors
    return 0 if ok else 1


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
