---
task: issue-link
intent: "Vínculo bidireccional contrato<->issue: campo issue, regla tc_lint y sync de labels."
issue: MauricioPerera/ccdd-gate#11
target: integrations/github/link.py
tests: tests/test_issue_link.py
spec_version: "0.1"
language: python
---

## Intent
Trazabilidad bidireccional contrato ↔ issue: un campo `issue` opcional en el front-matter, una
regla de lint que valida su formato, un helper `link status` que mapea en ambos sentidos, y un
sync de labels que refleja el estado del contrato en el issue sin pisar labels ajenas.

> Nota CCDD: regla en tc_lint (sustrato) + adaptador opcional (integrations/github/link.py).

## Interface
```
front-matter: issue?: "owner/repo#N" | URL github.com   ;  require_issue?: bool

tc_lint: regla tc-issue-ref — error si `issue` tiene formato inválido; con require_issue=true,
         warn si falta. Sin `issue`, no rompe nada (back-compat, opt-in).

link.py status --contract task.md   -> estado {drafted,lint_ok,tests_approved,gate_passed} + labels
link.py status --issue owner/repo#N -> contratos que lo referencian (ambas formas)
link.py sync-labels --contract task.md [--post]  -> diff de labels (idempotente)
Núcleos puros: parse_issue_ref, normalize_issue_ref, contracts_referencing, state_to_labels, diff_labels
```

## Invariants
- `issue` válido (owner/repo#N o URL) pasa lint; formato inválido -> error tc-issue-ref.
- `link status` mapea en ambos sentidos; URL y short se normalizan a `owner/repo#N`.
- sync de labels: idempotente y gestiona SOLO el prefijo `ccdd:` (no toca labels ajenas).
- `issue` y el sync son opcionales (back-compat). Sin LLM.

## Examples
- `issue: "MauricioPerera/ccdd-gate#11"` -> lint OK.
- estado {drafted,lint_ok} -> labels {ccdd:drafted, ccdd:lint-ok}.

## Do / Don't
- DO: normalizar URL/short para comparar; diff que preserva labels no-ccdd.
- DON'T: borrar labels ajenas; romper contratos sin `issue`.

## Tests
`tests/test_issue_link.py` (congelados, sin red): regla tc-issue-ref (válido/ inválido/ ausente/
require_issue), parse+normalize, issue->contratos, state_to_labels, diff idempotente y sin pisar.

## Constraints
- Adaptador opcional; gh con tokens por entorno. PARAR si un `issue` no parsea (no adivinar).
