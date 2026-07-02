# RC1 — gate-wrapper (anti-bypass por delegación trivial) + refactor de `gate()`

Rama: `audit-repairs`. Fecha: 2026-07-01.
Archivos tocados (regla de aislamiento respetada): `runners/task_gate.py`, `tests/test_gates.py` (sin cambios necesarios — la suite existente ya cubre regresión), `tests/test_wrapper_bypass.py` (nuevo). No se tocó `ccdd.py` ni ningún otro runner/test.

## 1. Detección implementada — `_gate_wrapper` (gate 1.7, default-ON)

**Problema verificado.** El gate mide SOLO la función target. Un implementador deja el target como
un pass-through trivial y esconde toda la complejidad en un sibling de módulo del MISMO archivo que
no es target de ningún contrato:

```python
def g(n):        # 15 ifs -> cyclomatic 16, NUNCA medido por el gate
    ...
def f(n):        # cyclomatic 1, medido -> PASS midiendo la cáscara
    return g(n)
```

`f` pasa el budget; `g` (la lógica real) es invisible. Bypass del árbitro.

**Fix.** Nuevo stage `_gate_wrapper(fm, target, fn_name, budget)` insertado en la cadena de `gate()`
JUSTO antes de `_gate_complexity`. Detección ESTRECHA (minimizar falsos positivos):

1. Parsea el AST del target y localiza la def del target con `sig_check._find_function`
   (respeta `target_line` para homónimos, igual que los demás gates).
2. Considera al target un "pass-through trivial" SOLO si su cuerpo (ignorando un docstring inicial)
   es EXACTAMENTE una sentencia `return <Call>` o `return await <Call>` (nada más). Helper
   `_is_trivial_delegator(fn_node)` -> devuelve el id del callee o None.
3. El callee debe ser un `ast.Name` (llamada directa `g(...)`) cuyo id sea una función definida a
   NIVEL DE MÓDULO en el MISMO archivo (helper `_module_level_funcs(tree)`). Se ignoran llamadas a
   atributos (`obj.m()`), builtins e importados/externos: esos NO son siblings contratibles.
4. Mide la complejidad del sibling con el MISMO backend que `_gate_complexity`
   (`metrics_backends.functions_metrics`, helper `_sibling_metric_row`). Si el sibling excede
   cualquier métrica del `budget` (vía `_over_budget`, fuente única del criterio sobre-budget,
   compartido con `_gate_complexity`) -> devuelve:
   ```json
   {"verdict":"INVALID","stage":"gate-wrapper",
    "detail":"el target delega en el sibling de módulo '<nombre>' (no contratado) que excede el budget; el gate no puede medir la lógica real",
    "sibling":"<nombre>","sibling_metrics":{...},"budget":{...}}
   ```
5. En caso contrario (sibling dentro de budget / target hace trabajo real / callee no es sibling de
   módulo / target no existe o no parsea) -> `None`: no aplica, deja seguir la cadena.

**Salida real del gate (bypass end-to-end, contrato válido):**
```json
{
  "verdict": "INVALID",
  "stage": "gate-wrapper",
  "detail": "el target delega en el sibling de módulo 'g' (no contratado) que excede el budget; el gate no puede medir la lógica real",
  "sibling": "g",
  "sibling_metrics": { "cyclomatic": 16, "nesting_depth": 1, "parameter_count": 1, "function_length": 32 },
  "budget": { "cyclomatic_max": 5, "nesting_max": 2, "params_max": 1, "lines_max": 12 }
}
```

## 2. Refactor de `gate()` — deuda de dogfooding

`gate()` tenía cyclomatic 15 (> budget propio 10) por la cadena de `or` con 12 etapas. Refactorizada
a un LOOP determinista sobre una lista de callables de etapa, preservando EXACTAMENTE el mismo
orden y semántica (primer no-None gana; PASS sólo si todas dan None y `_gate_complexity` da PASS).
El early-return de contract-lint/INVALID y la rama `kind:group` se conservan antes del loop, sin
tocar. `_gate_complexity` (último stage) siempre devuelve un veredicto, así que el loop retorna
dentro de la iteración final — resultado idéntico al histórico para todo contrato existente.

`_gate_complexity` se refactorizó para usar el helper `_over_budget` (fuente única del criterio);
los strings `over_budget` son byte-idénticos a la comprehension inline anterior.

## 3. Tests — `tests/test_wrapper_bypass.py` (4 casos, definición de hecho)

- **(a)** `def f(n): return g(n)` con `g` sibling de 15 ifs sobre budget -> `INVALID/gate-wrapper`
  (hoy daba PASS). Verifica además `sibling=="g"` y `sibling_metrics.cyclomatic > budget.cyclomatic_max`.
- **(b)** control: `g` dentro de budget (`return n`) -> `PASS/all` (wrapper no aplica).
- **(c)** control: target con trabajo real (`if n < 0: return -1` además de `return g(n)`) ->
  NO `gate-wrapper`, va a complexity -> `PASS/all`.
- **(d)** control: delegación a importado (`from math import sqrt; return sqrt(n)`, no sibling) ->
  NO `gate-wrapper`, va a complexity -> `PASS/all`.

Todos los contratos de test usan `require_test_approval: false` (para aislar el stage bajo prueba),
tests que pasan, secciones canónicas y `PARAR y reportar si...` (lintean limpio).

## 4. Conteo final

Suite completa (`python -m unittest discover -s tests`), dos corridas:
```
Ran 430 tests in 11.887s
OK
```
```
Ran 430 tests in 10.720s
OK
```
**0 failures / 0 errors** (426 existentes + 4 nuevos). Ningún contrato/ejemplo existente rompe:
`python runners/task_gate.py examples/sandbox/task.md` -> `PASS/all`;
`python runners/task_gate.py examples/batch/popcount/task.md` -> `PASS/all`
(`decode_instruction` y `popcount` hacen trabajo real, no son wrappers -> no afectados).

## 5. Complejidad de `gate()` y funciones nuevas

```
gate                  cyc= 6  nest= 2  lines= 36   (era 15; budget 10 — deuda saldada)
_gate_wrapper         cyc= 9  nest= 1  lines= 27   (budget 10/3/41)
_is_trivial_delegator cyc= 6  nest= 1  lines= 14
_is_docstring         cyc= 3  nest= 0  lines= 4
_callee_name          cyc= 3  nest= 0  lines= 3
_module_level_funcs   cyc= 3  nest= 0  lines= 6
_sibling_metric_row   cyc= 5  nest= 1  lines= 10
_over_budget          cyc= 4  nest= 0  lines= 6
_gate_complexity      cyc= 7  nest= 1  lines= 12   (refactor con _over_budget)
```
`gate()` cyclomatic = **6** (≤ 10). Todas las funciones nuevas bajo budget.

## 6. Trade-offs / limitaciones de la detección

- **Depth-1 intencional.** Solo persigue delegadores de 1 sentencia a un sibling complejo. NO
  sigue cadenas delegador->delegador (`f -> g -> h` con `h` complejo y `g` también trivial): `f`
  delega en `g` (trivial, dentro de budget) -> wrapper no dispara, y `g` no es target de ningún
  contrato, así que `h` queda invisible. Documentado en el docstring de `_gate_wrapper`. Ampliar a
  depth-N aumentaría los falsos positivos (cualquier helper legit `return helper(x)` se volvería
  sospechoso) y no se pide en esta tarea.
- **Sólo siblings de módulo del MISMO archivo.** Delegación a un helper de OTRO archivo (importado)
  no se detecta (caso (d) es NO-gate-wrapper por diseño): el gate es por-archivo y un sibling en
  otro módulo no es medible aquí sin un contrato que lo gobierne — ésa es responsabilidad del
  orquestador (composición `kind:group`), no del gate de función.
- **Sólo `return <Call>` / `return await <Call>` exacto.** Un delegador que envuelva el resultado
  (`return g(n) + 0`, `return (g(n),)`, `return g(n) if cond else 0`) ya NO es un pass-through
  trivial -> wrapper cede. Es el costo de la detección estrecha; esos casos pasan a complexity,
  que mide la cáscara (hueco residual aceptado).
- **Callee debe ser `ast.Name` directo.** `return obj.g(n)` (atributo) no cuenta: un método de
  instancia no es un sibling de módulo contratible.
- **Falsos positivos: ninguno esperado en los ejemplos.** `decode_instruction`, `popcount` y
  funciones reales que deleguen en un helper simple dentro de budget pasan intactas (caso (b)).