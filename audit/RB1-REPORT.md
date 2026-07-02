# RB1 — Reporte de reparación de auditoría (bypass del árbitro)

**Estado: LANZADO. Suite en verde (426 tests, 0 failures / 0 errors), dos corridas.**
Los 4 bugs están fixados, los 5 ejemplos re-firmados con el algoritmo unificado, y los 3
tests de regresión añadidos. `task_gate.py examples/sandbox/task.md` y
`examples/batch/popcount/task.md` dan PASS real bajo el gate fixeado.

## Los 4 bugs fixados

1. **[CRÍTICO] Bypass por rebind** — `_gate_rebind(fm, target, fn_name)` en `task_gate.py`
   (helper `_rebind_target_name`): detecta reasignación a nivel de módulo del nombre target
   (`ast.Assign`/`ast.AnnAssign` con target `Name(fn_name)` aparte de su `def`) →
   `INVALID/gate-rebind: "el nombre del target se reasigna a nivel de módulo; el gate no
   puede medir la función real"`. Va en la cadena justo antes de `_gate_complexity`.
   Antes: `def f(n): return n` + `def _real(n): <9 ifs>` + `f = _real` → PASS midiendo la
   cáscara trivial (cyclomatic 1). Ahora: INVALID/gate-rebind.

2. **[CRÍTICO] Mismatch de hash** — Unifiqué el algoritmo en ambos lados a **sha256 de bytes
   normalizados a LF** vía una única función `raw_digest(text)` en `approve_tests.py`,
   importada por `task_gate.py`:
   - `approve_tests.raw_digest(text) = sha256(text.replace("\r\n","\n").replace("\r","\n").encode("utf-8"))`.
   - `approve_tests.main` firma con `raw_digest` (dejó de usar `semantic_hash.get_semantic_hash`).
   - `task_gate._gate_test_approval` verifica con `approve_tests.raw_digest` (dejó de usar
     `hashlib.sha256(tests.read_bytes())`).
   - Criterio idéntico al de `eval_gate.dataset_digest` (portabilidad CRLF/LF). Firma y
     verificación usan el MISMO código → imposible el mismatch. `approve_tests --check` y el
     gate coinciden sobre un test intacto.

3. **[CRÍTICO/ALTO] Oráculo vacuo** — secure-by-default:
   - `_gate_test_approval`: `if fm.get("require_test_approval", True) is False: return None`.
     Default-ON; un autor sale explícitamente con `require_test_approval: false`.
   - `tc_lint.r_tests_frozen` reforzada: en vez de substring, parsea el AST del test y exige
     `ast.ImportFrom`/`ast.Import` del módulo target (`Path(target).stem`) O `ast.Call` a
     `fn_name` (Name o Attribute). Un test que solo menciona fn en un comentario → error
     `tc-tests-frozen`. No-Python/no-parseable degrada a substring (back-compat). Mismo
     nombre de regla y nivel (error). Helpers: `_imports_target_module`, `_calls_fn`,
     `_test_references_fn`.

4. **[MEDIO] Crash por SyntaxError** — `_gate_complexity` ya no muere con traceback si el
   target no parsea: el parse+measure se aisló en `_target_metrics(fm, target)` que atrapa
   `SyntaxError` y devuelve `(None, {"verdict":"FAIL","stage":"gate2-complexity","detail":
   "el target no parsea: ..."})`. `_gate_complexity` propaga ese dict → veredicto JSON,
   no traceback.

## Cómo unifiqué el hash

Una única función `raw_digest(text)` en `approve_tests.py` (módulo liviano), importada por
`task_gate.py`. Firma y verificación usan el MISMO código → imposible el mismatch.
LF-normaliza antes de hashear para que la firma sea independiente del checkout CRLF vs LF
del repo (criterio idéntico al de `eval_gate.dataset_digest`).

## Ejemplos re-firmados (tarea 4)

`python runners/approve_tests.py <task.md>` regenera `tests_sha256` con `raw_digest`:

| ejemplo | tests_sha256 (raw_digest LF) |
|---|---|
| examples/sandbox/task.md | cdf60f86f46822a9cd1201b7719e1e524846a18f70ad3caee8c9a4da3914f8ad |
| examples/batch/popcount/task.md | 697191cd53a22f8b577f7e495f188b1eb779fb2648be2711747701211bb1cbd1 |
| examples/batch/clamp/task.md | 57ef5e37f50d4725a3cf4bbc762cb973fe709cb5a8396e7b6a487f81c516eeac |
| examples/batch/chunk/task.md | b54d89e6f8e9b4438d25cff657a85b3ce414a7d1d2527bda7f96519a62258154 |
| examples/batch/hamming/task.md | 84497fb903df34bc09eadfcfe685e791ce681c191142ea46f2eb486c145bf64d |

Los tests de los 4 batch son LF-only, así que `raw_digest` (LF) coincide con el hash de
bytes crudos que ya tenían a HEAD → esos 4 `tests_sha256` no cambiaron. El test de sandbox
tiene CRLF, así que su hash sí cambió (c339d9cf… → cdf60f86…): esto es exactamente el bug
que el algoritmo unificado arregla (firma CRLF vs verificación LF ya coinciden). Los tests
mismos no se tocaron, solo `tests_sha256`.

## Tests añadidos

- `tests/test_rebind_bypass.py` (nuevo): target con `f = _real` (real complejo de 9 ifs que
  satisface `f(1)==1` para pasar gate1-tests) → `INVALID/gate-rebind` (antes PASS midiendo
  la cáscara); control sin rebind → PASS.
- `tests/test_gates.py::TestApproveGateIntegration`: firma con `approve_tests` → `task_gate`
  PASS; tamperear el test sin re-firmar → `INVALID/test-approval`. Regresión directa del
  mismatch de hash. + fix del bug enshrinado en `test_invalid_unapproved_tests`: ahora
  quita la línea `tests_sha256` (genuinamente sin aprobar) en vez de apoyarse en el
  mismatch semantic-vs-raw que ya no existe.
- `tests/test_tc_lint_rules.py::test_tests_only_mention_in_comment_flagged`: un test que
  solo menciona fn en un comentario → `tc-tests-frozen` error.

## Ajuste de fixtures (tarea 3 — secure-by-default)

Contratos de test que testean OTRA etapa → `require_test_approval: false` explícito, para
que el default-ON no los haga morir en test-approval antes de la etapa que ejercen:
`test_purity_gate`, `test_mutdef_gate`, `test_bareexcept_gate`, `test_assert_gate`,
`test_nonecmp_gate`, `test_deps_gate`, `test_homonymous_target`, `test_signature_gate` y
`examples/sandbox/loop_demo/task.md` (harness del loop CEFL del orquestador — testea el
torneo/feedback, no test-approval).

## Conteo final de suite

Dos corridas completas, idénticas:

```
Ran 426 tests in 10.962s

OK
```

Salida real (últimas líneas) de `python -m unittest discover -s tests`:
```
........................................[ci-gate] posting falló (no afecta el veredicto del gate): gh read-only
.......................................................................................body
.FIRMADO  test_decode_instruction.py  tests_sha256=cdf60f86...   (side-effect de TestApproveGateIntegration)
...............................................................sin backend de métricas para m.cobol ...
..........................................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 426 tests in 10.962s

OK
```

(La línea `FIRMADO …` es stdout de `TestApproveGateIntegration.test_signed_test_is_accepted`
llamando a `approve_tests.main` sobre un tempdir — ruido de test, no un fallo. El
`[ci-gate] posting falló` y `sin backend … cobol` son mensajes esperados de otros tests.)

Ejemplos bajo el gate fixeado:
```
$ python runners/task_gate.py examples/sandbox/task.md
{ "verdict": "PASS", "stage": "all", "function": "decode_instruction",
  "metrics": {"cyclomatic": 3, "nesting_depth": 1, "parameter_count": 2, "function_length": 11},
  "budget": {"cyclomatic_max": 8, "nesting_max": 2, "params_max": 2, "lines_max": 20} }

$ python runners/task_gate.py examples/batch/popcount/task.md
{ "verdict": "PASS", "stage": "all", "function": "popcount",
  "metrics": {"cyclomatic": 2, "nesting_depth": 1, "parameter_count": 1, "function_length": 6},
  "budget": {"cyclomatic_max": 5, "nesting_max": 2, "params_max": 1, "lines_max": 12} }
```

## Budget de complejidad (restricción del task)

Medido con `metrics_backends.functions_metrics` sobre `task_gate.py`:

| función | cyclomatic | lines | budget (cyc≤10 / lines≤41) |
|---|---|---|---|
| `_gate_test_approval` | 5 | 16 | OK |
| `_gate_rebind` | 4 | 12 | OK |
| `_rebind_target_name` | 7 | 9 | OK |
| `_target_metrics` | 3 | 12 | OK (helper extraído) |
| `_gate_complexity` | 10 | 14 | OK (en budget; el try/except se aisló en `_target_metrics`) |
| `gate` | 15 | 24 | **ver trade-off** |

`_gate_complexity` estaba a 10 en HEAD; el `try/except SyntaxError` lo llevaba a 11. Lo
bajé de vuelta a 10 aislando `not target.exists()` + `try/except` en el helper
`_target_metrics` (neto de ramas en `_gate_complexity`: −1 `if not exists` +1 `if err` = 0).

## Trade-offs

- **`gate` (composición) cyc=15 > 10.** Ya estaba a 14 en HEAD: es la raíz de composición,
  una sola expresión `return (g0(...) or g1(...) or … or _gate_rebind(...) or _gate_complexity(...))`
  donde cada rama es un `or`-delegado a un helper extraído. La cláusula `_gate_rebind` es
  obligatoria (bug #1). No la reestructuré a un loop porque (a) no está en el scope del
  bug, (b) ya era no-conforme a HEAD, (c) cada rama es un delegado trivial a un helper, (d)
  un refactor a loop cambiaría el patrón de composición deliberado del proyecto y arriesga
  comportamiento. Reportado en vez de forzado, per "PARA y reporta el conflicto (no fuerces)".
- **`require_test_approval` default-ON** es un cambio de comportamiento: todo contrato con
  tests pero sin `tests_sha256` válido pasa a `INVALID/test-approval`. Re-firma de ejemplos
  y `require_test_approval: false` en fixtures de otra etapa son obligatorios (hechos).
- **`r_tests_frozen` AST-strict** podría rechazar tests Python válidos que referencian fn
  de formas exóticas (p.ej. solo vía `getattr`). Mitigado: `ImportFrom` del módulo target O
  `Call` directo cubren los patrones reales; no-Python degrada a substring.
- **`raw_digest` (LF) vs `read_bytes` (CRLF si aplica):** un test firmado en checkout LF y
  verificado en checkout CRLF ahora coincide (antes no). Esto es lo que arregla el bug #2.