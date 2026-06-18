---
task: decompose-subissues
intent: "Materializar task-contracts atómicos como sub-issues de GitHub enlazados al padre."
issue: MauricioPerera/ccdd-gate#15
target: integrations/github/decompose.py
tests: tests/test_decompose.py
spec_version: "0.1"
language: python
---

## Intent
Un epic/feature no es un task-contract (sin firma única ni tests congelados). El feature queda
como issue PADRE; cada unidad atómica baja a un task-contract + su sub-issue. Esta herramienta
NO decide la descomposición (la decide el autor): solo MATERIALIZA los sub-issues a partir de los
contratos atómicos dados y enlaza contrato↔sub-issue en ambos sentidos.

> Nota CCDD: adaptador opcional (gh). Sin LLM (solo materializa).

## Interface
```
build_subissue(task_path) -> {slug, title, body, contract}   # body con marker idempotente
plan(contract_paths, existing_issues) -> [{slug, action: create|skip, existing_number}]
set_issue_field(contract_text, ref) -> text   # vínculo inverso en el front-matter
find_existing(issues, slug) -> number|None
execute(parent, planned, post) -> resultados   # crea+enlaza vía gh sub_issues API
CLI: decompose.py --parent owner/repo#9 --contracts a.md b.md [--non-atomic "X"] [--post]
```

## Invariants
- Padre + N sub-issues; cada contrato atómico referencia su sub-issue y viceversa.
- Idempotente: re-ejecutar no duplica (detecta por marker `<!-- ccdd-task:<slug> -->`).
- Unidades NO atómicas: solo se reportan (se quedan como issues normales).
- Dry-run (sin --post) no muta los contratos ni crea nada. Sin LLM.

## Examples
- contrato task=chunk-list -> sub-issue "[chunk-list] <intent>" + marker.
- re-ejecutar con el sub-issue ya existente -> action=skip.

## Do / Don't
- DO: marker por task para idempotencia; vínculo bidireccional.
- DON'T: decidir la atomicidad por el autor; duplicar sub-issues.

## Tests
`tests/test_decompose.py` (congelados, sin red): build_subissue, plan create/skip idempotente,
set_issue_field (inserta/reemplaza una vez), y dry-run que no muta el contrato.

## Constraints
- Adaptador opcional; gh con tokens por entorno. PARAR si un contrato no trae `task`.
