---
task: scaffold-from-issue
intent: "Esqueleto de task-contract desde un issue de GitHub, con placeholders explícitos."
issue: MauricioPerera/ccdd-gate#10
target: integrations/github/scaffold.py
tests: tests/test_scaffold.py
spec_version: "0.1"
language: python
---

## Intent
Generar un esqueleto de task-contract a partir de un issue (título/cuerpo/labels), para que el
autor parta de la intención ya capturada. NO inventa interfaz ni tests: deja `TODO` a propósito,
de modo que `tc_lint` lo reporte como incompleto (no falsamente verde).

> Nota CCDD: adaptador opcional (integrations/github/), sin tocar el core. Determinista, sin LLM.

## Interface
```
scaffold.scaffold(issue_dict, repo=None) -> str   # texto del task-contract esqueleto
scaffold.kebab(title) -> slug                      # task en kebab-case del título
scaffold.normalize_ref(issue, repo) -> "owner/repo#N" | URL | None
CLI: scaffold.py --issue owner/repo#N [-o f]  |  --from-json issue.json --repo o/r [-o f]
```

## Invariants
- El esqueleto tiene front-matter base (task, intent, issue, budget, spec_version) + las 7 secciones.
- Es INCOMPLETO por diseño: `tc_lint` reporta errores (tc-signature-valid, tc-tests-frozen) — nunca
  falsamente verde.
- El campo `issue` generado es de formato válido (no dispara tc-issue-ref).
- Funciona offline con un JSON pegado (sin red/credenciales), para CI/test.
- Determinista, sin LLM.

## Examples
- issue {title:"feat: X", number:99, html_url:...} -> task `feat-x`, issue con la URL.
- `kebab("Hello World!")` -> "hello-world".

## Do / Don't
- DO: placeholders TODO explícitos; importar el cuerpo del issue como contexto comentado.
- DON'T: inventar firma/tests (haría el contrato falsamente verde).

## Tests
`tests/test_scaffold.py` (congelados, sin red): kebab, normalize_ref, contenido del esqueleto,
y que tc_lint lo marca incompleto (tc-signature-valid + tc-tests-frozen), no verde.

## Constraints
- Adaptador opcional; online vía gh, offline vía JSON. Sin LLM (scaffolding determinista).
