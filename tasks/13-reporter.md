---
task: github-reporter
intent: "Veredicto determinista del gate como comentario idempotente en issue/PR."
issue: MauricioPerera/ccdd-gate#13
target: integrations/github/reporter.py
tests: tests/test_reporter.py
spec_version: "0.1"
language: python
---

## Intent
Publicar el veredicto determinista del gate (task_gate/complexity_gate) como artefacto legible en
GitHub, reutilizable por la Action (#12) y el orquestador (#14). El render es función PURA (mismo
JSON -> mismo Markdown), sin nada no determinista, para actualizar idempotentemente un comentario.

> Nota CCDD: capa adaptadora opcional (integrations/github/); el core sigue emitiendo solo JSON.

## Interface
```
reporter.render(verdict, contract=None, target=None) -> str   # Markdown determinista + MARKER oculto
reporter.find_marked_comment(comments, marker=MARKER) -> id|None   # pura, testeable sin red
reporter.upsert_comment(repo, issue, body, marker=MARKER) -> {action, comment_id?}   # vía gh
CLI: python integrations/github/reporter.py verdict.json [--contract C] [--repo o/r --issue N --post]
```

## Invariants
- Determinista: `render(v) == render(v)` (sin timestamps/aleatoriedad).
- Idempotente: `upsert_comment` ACTUALIZA el comentario con MARKER si existe; si no, crea uno.
- Offline: sin `--post` imprime el Markdown (no toca la red). Online: publica vía `gh`.
- Sin LLM (formatea, no razona). El core del gate no cambia (sigue emitiendo JSON).

## Examples
- verdict PASS -> encabezado ✅ + tabla métricas vs budget.
- verdict FAIL gate1 -> lista `over_budget`.

## Do / Don't
- DO: marker HTML oculto para detectar y actualizar el comentario propio.
- DON'T: spamear (crear un comentario nuevo por corrida); meter LLM o timestamps.

## Tests
`tests/test_reporter.py` (congelados, sin red): determinismo del render, contenido PASS/FAIL/
INVALID, marker, y selección de comentario por marker (find_marked_comment).

## Constraints
- Adaptador opcional; tokens por entorno (gh), nunca en el repo.
- PARAR y reportar si el JSON de veredicto no trae la forma mínima (verdict/stage).
