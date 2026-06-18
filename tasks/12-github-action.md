---
task: github-action-gate
intent: "GitHub Action que corre tc_lint + task_gate en PR y bloquea si no pasa."
issue: MauricioPerera/ccdd-gate#12
target: integrations/github/ci_gate.py
tests: tests/test_ci_gate.py
spec_version: "0.1"
language: python
---

## Intent
Gate en CI: ningún PR que toque task-contracts (o su código objetivo) entra sin pasar tc_lint +
task_gate (complejidad ≤ budget + tests congelados + firma). Publica el veredicto vía el Reporter
(#13). Determinista, sin LLM en CI (el gate es el árbitro).

> Nota CCDD: adaptador opcional; usa el GITHUB_TOKEN del runner, sin secretos en el repo.

## Interface
```
.github/workflows/ccdd-gate.yml   # workflow en pull_request (+ workflow_call), copiable
integrations/github/ci_gate.py:
  is_contract(path) -> bool
  contracts_for_changed(changed_files, root) -> [contratos afectados]   # contrato o target cambiado
  run(paths) -> [{contract, verdict}]
  overall_pass(results) -> bool
  combined_report(results) -> Markdown (un único MARKER, idempotente)
  CLI: ci_gate.py [contratos] | --changed-against ref [--repo o/r --issue N --post]
  exit 0 si todos PASS, 1 si alguno FAIL/INVALID
```

## Invariants
- Contrato roto o complejidad > budget ⇒ exit 1 (check rojo, merge bloqueado con branch protection).
- PR limpio ⇒ exit 0 con resumen de métricas.
- Descubre los contratos del diff (el .md o su `target`); sin contratos afectados ⇒ PASS no-op.
- El reporte combinado tiene un solo MARKER (idempotente vía Reporter). Sin LLM.

## Examples
- PR que cambia `examples/.../task.md` con budget apretado ⇒ FAIL.
- PR que cambia solo el código objetivo ⇒ corre el contrato de ese target.

## Do / Don't
- DO: descubrir por diff (contrato o target); fallar cerrado; comentar idempotente.
- DON'T: meter LLM en CI; usar secretos (solo GITHUB_TOKEN del runner).

## Tests
`tests/test_ci_gate.py` (congelados, sin red): is_contract, contracts_for_changed (contrato/
target/unrelated), PASS limpio, FAIL por budget, reporte con un solo marker y caso vacío.

## Constraints
- Workflow copiable a repos consumidores (documentado en README). Adaptador opcional.
- PARAR y reportar si no se puede resolver la rama base para el diff.
