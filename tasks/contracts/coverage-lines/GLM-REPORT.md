# GLM-REPORT — task: function-lines

- **Veredicto del gate:** PASS
- **Intentos del implementador (glm-5.2:cloud):** 3
- **Target:** `runners/coverage_check.py` → `function_lines(source, fn_name, target_line=None) -> set`
- **Oráculo:** `tests/test_coverage_check.py` (congelado, 9 casos: plano, branch, excluye def, async, no encontrada, parse error, target_line disambigua, target_line primera def).

## Métricas finales (gate)
| métrica | valor | tope |
|---|---|---|
| cyclomatic | 6 | 8 |
| nesting_depth | 2 | 3 |
| parameter_count | 3 | 3 |
| function_length | 19 | 25 |

Dentro de budget en todos los ejes. No requirió extracción de sub-funciones por budget (aunque se añadieron `_find_function` y `_is_statement` como auxiliares por claridad).

## Resumen de la implementación
1. `ast.parse(source)`; `SyntaxError` → `set()`.
2. `_find_function` localiza la `FunctionDef`/`AsyncFunctionDef` de `fn_name` honrando `target_line` (== lineno si se da, si no la primera). `None` → `set()`.
3. `ast.walk(target_function)` recolecta el `lineno` de cada nodo que sea una sentencia (`_is_statement`): assign/return/expr/if/for/while/with/try/match/pass/break/continue/etc. — recursivo, cubre ifs/fors/anidadas.
4. `lines.discard(target_function.lineno)` excluye la línea del `def`. Los decoradores no son sentencias, así que tampoco entran.
5. Solo stdlib (`ast`). Sin `__import__`, sin `print`, sin I/O, sin estado global, sin ejecutar el código analizado.

## Patrón seguido
`_find_function` imita el de `runners/sig_check.py` (mismo criterio: target_line disambigua homónimas; sin target_line → primera).

## Notas
- Contrato y tests no modificados (congelados).
- Solo se editó `runners/coverage_check.py`.