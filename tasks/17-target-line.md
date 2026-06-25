---
task: target-line-disambiguation
intent: "Aislar la def objetivo del gate cuando varias funciones comparten el nombre."
issue: MauricioPerera/ccdd-gate#41
target: runners/task_gate.py
tests: tests/test_homonymous_target.py
spec_version: "0.1"
language: python
---

## Intent
`task_gate` resolvía la función objetivo por NOMBRE con un dict (last-wins): con métodos homónimos en
varias clases (set/get/search/__init__…) medía la última definición del archivo, no la del contrato,
dando PASS/FAIL engañosos. La selección debe desambiguarse por algo más que el nombre.

> Nota CCDD: determinista, sin LLM, todos los backends (Python AST + tree-sitter). No toca
> lint_results.schema.json (la `line` ya está en cada finding).

## Interface
```
runners/task_gate.py
  _select_target_fn(fm, fn_name, matches, target_name) -> fila de métricas | dict de error
    0 matches            -> FAIL (la función no está en el target)
    target_line presente -> selecciona la def cuya line coincide; sin match -> INVALID (candidate_lines)
    >1 match sin target_line -> INVALID (ambiguo, candidate_lines); nunca medir la última en silencio
    1 match              -> idéntico al histórico (back-compat)
task-contract: nuevo campo opcional `target_line: N` (entero, línea de la def objetivo)
schema: task_contract.schema.json declara target_line (integer, minimum 1)
```

## Invariants
- La `line` es única por def y la exponen todos los backends → desambiguador universal.
- Sin colisión (un solo match): comportamiento idéntico al actual (selección por nombre).
- Con ambigüedad y sin desambiguador: INVALID, no un veredicto sobre la def equivocada.
- Determinista: mismo input → mismo veredicto.

## Examples
- 2 clases con método `set` (ciclo 1 y ciclo 6), contrato sin target_line → INVALID (candidate_lines [2,6]).
- mismo target con `target_line: 2` (Simple.set) → mide ciclo 1 → PASS.
- `target_line: 6` (Compleja.set) → FAIL por budget.
- target con una sola def `set`, sin target_line → PASS (back-compat).

## Do / Don't
- DO: declarar target_line cuando el target tiene métodos homónimos (OOP).
- DON'T: medir la última def del nombre en silencio; cambiar el schema de lint_results.

## Tests
`tests/test_homonymous_target.py` (congelados, sin LLM): ambiguo → INVALID; target_line correcto →
mide la def correcta (PASS simple / FAIL compleja); single match → back-compat; target_line sin match → INVALID.

## Constraints
- Sin LLM. Aplica a todos los backends. PARAR si target_line no coincide con ninguna def del nombre.
- `target_qualifier: Clase.método` queda como posible mejora futura (requiere nombre cualificado en ambos backends + conformancia).
