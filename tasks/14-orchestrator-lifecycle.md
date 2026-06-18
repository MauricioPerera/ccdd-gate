---
task: orchestrator-lifecycle
intent: "Conectar el orquestador con el ciclo de vida del issue (ccdd:ready -> PR/escalado/split)."
issue: MauricioPerera/ccdd-gate#14
target: integrations/github/lifecycle.py
tests: tests/test_lifecycle.py
spec_version: "0.1"
language: python
---

## Intent
Conectar el orquestador (pequeño implementa → gate → reintenta → escala) con el ciclo de vida de
un issue de GitHub, SIN que el loop del orquestador sepa de GitHub: recibe un callback opcional
con su veredicto determinista; el adaptador traduce a transiciones de label + acciones.

> Nota CCDD: el LLM solo está en el worker del orquestador (ya es así); gate y reporting son
> deterministas. Adaptador opcional.

## Interface
```
orchestrator.implement(..., on_result=None)   # callback opcional (result, task_path); default local
lifecycle.decide_transition(result) -> {action, label, reason}   # determinista, puro
lifecycle.label_transition(current, target) -> (to_add, to_remove)  # reversible, solo ciclo de vida
lifecycle.ready_refs(issues, repo) -> [owner/repo#N]   # issues etiquetados ccdd:ready
lifecycle.process(result, issue_ref, contract, branch, post) -> steps   # aplica transición
lifecycle.make_callback(issue_ref, ...) -> on_result callback
```

Mapa: PASS->open_pr+ccdd:in-review · ESCALATE->comment+ccdd:escalated · FAIL->comment+ccdd:needs-split
· INVALID->comment+ccdd:needs-split.

## Invariants
- Un issue ccdd:ready con contrato válido y gate verde produce un PR enlazado (`Closes #N`).
- Transiciones de label deterministas y reversibles; gestionan SOLO el set de ciclo de vida
  (ccdd:ready/in-review/escalated/needs-split), no pisan otras labels.
- Sin callback (default None), el orquestador corre igual en local (no toca GitHub).
- Sin LLM en el adaptador; el gate/reporting son deterministas.

## Examples
- result PASS -> acción open_pr, label ccdd:in-review, comentario del Reporter.
- result ESCALATE -> comentario con motivo, label ccdd:escalated.

## Do / Don't
- DO: orquestador agnóstico de GitHub vía callback; transiciones reversibles.
- DON'T: meter GitHub en el loop del orquestador; pisar labels ajenas.

## Tests
`tests/test_lifecycle.py` (congelados, sin red): decide_transition (4 resultados), label_transition
(reversible/idempotente/no pisa), ready_refs, process dry-run (PASS->PR preview, ESCALATE->comment),
y el callback del orquestador (dispara; default None idéntico en local).

## Constraints
- Todo el contacto con GitHub pasa por el adaptador (gh, token por entorno).
- PARAR y reportar si el resultado del orquestador no trae `result`.
