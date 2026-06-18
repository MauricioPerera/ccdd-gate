#!/usr/bin/env python3
"""scaffold.py — genera el ESQUELETO de un task-contract desde un issue de GitHub. Sin LLM.

Captura la intención ya escrita en el issue (título/cuerpo/labels) y emite un `.md` con el
front-matter base (`task` en kebab-case del título, `intent` del título, `issue:` con la ref,
`spec_version`, `budget` por defecto) + las secciones obligatorias con PLACEHOLDERS explícitos.

NO inventa interfaz ni tests: deja `TODO` a propósito, de modo que `tc_lint` lo reporte como
INCOMPLETO de forma clara (no falsamente verde). El autor (humano/modelo grande) lo completa.

Capa adaptadora opcional. Online lee el issue vía `gh`; offline acepta un JSON pegado del issue
(para CI/test, sin red).

  scaffold.py --issue owner/repo#N [-o task.md]
  scaffold.py --from-json issue.json --repo owner/repo [-o task.md]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_BUDGET = "{ cyclomatic_max: 8, nesting_max: 2, params_max: 3, lines_max: 30 }"
_SECTIONS = [
    ("## Intent", "TODO: una frase atómica de QUÉ hace (no el cómo). Éxito = pasa los property-tests."),
    ("## Interface", "```\nin:  TODO\nout: TODO\nerror: TODO\n```"),
    ("## Invariants", "- TODO: invariante 1 que los tests deben verificar."),
    ("## Examples", "- TODO: input → output\n- TODO: input → output"),
    ("## Do / Don't", "- DO: TODO\n- DON'T: TODO"),
    ("## Tests", "TODO: describe el property-test congelado con oráculo independiente."),
    ("## Constraints", "- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz."),
]


def kebab(text, maxlen=50):
    """Título -> slug kebab-case determinista para el campo `task`."""
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "task")


def normalize_ref(issue, repo=None):
    """Ref canónica owner/repo#N a partir del dict del issue (+ repo si no trae html_url)."""
    url = issue.get("html_url")
    if url and "github.com/" in url:
        return url
    num = issue.get("number")
    if repo and num is not None:
        return f"{repo}#{num}"
    return None


def scaffold(issue, repo=None):
    """dict de issue -> texto del task-contract esqueleto (con placeholders TODO explícitos)."""
    title = issue.get("title", "TODO")
    ref = normalize_ref(issue, repo)
    labels = [l["name"] if isinstance(l, dict) else l for l in issue.get("labels", [])]
    fm = ["---",
          f"task: {kebab(title)}",
          f'intent: "{title}"',
          "target: TODO.py            # TODO: archivo objetivo",
          'signature: "TODO: def nombre(args) -> retorno"   # TODO: firma real',
          f"budget: {DEFAULT_BUDGET}",
          "deps_allowed: []",
          'forbids: []                # TODO: qué prohibir',
          "tests: TODO_test.py        # TODO: property-tests congelados (deben existir)"]
    if ref:
        fm.append(f'issue: "{ref}"')
    if labels:
        fm.append(f"# labels del issue: {', '.join(labels)}")
    fm += ['spec_version: "0.1"', "---", ""]
    body = []
    issue_body = (issue.get("body") or "").strip()
    if issue_body:
        body += ["<!-- contexto importado del issue (recórtalo al completar):", issue_body, "-->", ""]
    for header, placeholder in _SECTIONS:
        body += [header, placeholder, ""]
    return "\n".join(fm) + "\n".join(body).rstrip() + "\n"


def fetch_issue(ref):
    """Lee el issue vía gh. ref = owner/repo#N."""
    repo_part, num = ref.split("#", 1)
    r = subprocess.run(["gh", "api", f"repos/{repo_part}/issues/{int(num)}"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"gh falló: {(r.stderr or r.stdout).strip()}")
    return json.loads(r.stdout)


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="scaffold", description="Esqueleto de task-contract desde un issue.")
    ap.add_argument("--issue", help="owner/repo#N (online, vía gh)")
    ap.add_argument("--from-json", dest="from_json", help="JSON del issue pegado (offline)")
    ap.add_argument("--repo", help="owner/repo (para --from-json sin html_url)")
    ap.add_argument("-o", "--out", help="archivo de salida (default: stdout)")
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])
    if a.from_json:
        issue = json.loads(Path(a.from_json).read_text(encoding="utf-8"))
    elif a.issue:
        issue = fetch_issue(a.issue)
        a.repo = a.repo or a.issue.split("#", 1)[0]
    else:
        print("usa --issue owner/repo#N o --from-json file.json", file=sys.stderr)
        return 2
    text = scaffold(issue, repo=a.repo)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"escrito: {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
