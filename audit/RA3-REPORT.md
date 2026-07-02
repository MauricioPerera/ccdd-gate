# RA3 — Reparaciones de auditoría sobre orchestrator.py y measure.py

Rama: `audit-repairs`. Alcance respetado: sólo se editaron `runners/orchestrator.py`,
`runners/measure.py`, `tests/test_orchestrator_cefl.py` (nuevo), `tests/test_measure.py` (nuevo)
y, por fuerza mayor, `examples/sandbox/loop_demo/task.md` (detallado abajo). No se tocaron
`task_gate.py`, `complexity_mcp.py`, los checks, `rules_gate.py` ni `ci_gate.py`.

## Qué se arregló

### 1. [ALTO] Eliminado E3 "Entropía / auditoría criptográfica" (security theater)
**Decisión: eliminado por completo** (no sólo desactivado para stub). No aportaba seguridad
real: el nonce se le DICTABA al modelo en el mismo prompt donde se le pedía copiarlo, y luego
`_e3_verdict` degradaba a FAIL cualquier PASS que no lo incluyera. Cero valor criptográfico;
y el provider `stub` (archivos pre-autorados deterministas) no puede incluir un nonce aleatorio,
así que todo candidato stub bueno se degradaba a FAIL/ESCALATE.

Cambios concretos en `orchestrator.py`:
- Quitados `import secrets` e `import hashlib`.
- `build_prompt(fm, body, feedback)` ya no recibe `nonce` ni inyecta la sección "E3 Entropy".
- Eliminada `_e3_verdict`. `_evaluate_candidates(p, target, candidates_code)` ya no aplica E3.
- `run_rounds` ya no genera nonce/SHA256 ni imprime `[E3 Entropy] ... SHA256=...`.
- Eliminado el campo `e3_hash` de la telemetría por intento.

### 2. [MEDIO] Torneo determinista en empates
`_generate_candidates` preserva el **índice de envío** de cada futuro y reordena los
resultados por ese índice tras recolectar con `as_completed` (que devuelve por orden de
finalización, i.e. jitter de red). El torneo (`_pick_best`, refactorizado a helper testeable)
usa `min(..., key=(get_complexity_score(v), index))`: ante empate de score gana el de menor
índice de envío. El ganador es función solo del código, no del tiempo de red.

### 3. [MEDIO] `get_complexity_score` incluye `function_length`
Antes sumaba `cyclomatic + nesting_depth + parameter_count`, ignorando `function_length`
(`lines_max` del budget). Ahora suma las cuatro, para que el torneo respete todas las
métricas del budget y no premie un candidato más largo solo por empatar en el resto.

### 4. [MEDIO] `measure.py`: `api_saving_pct` honesto
Antes reportaba `api_saving_pct: 100.0` sobre corridas fallidas y sobre stub (el 100% salía
de que el modelo pequeño cuesta $0 por definición, no de un ahorro medido). Ahora:
- `api_saving_pct` se reporta como **número** sólo con tokens **MEDIDOS** (usage real del
  provider) Y al menos un PASS Y `big_loop_usd > 0`. En caso contrario: **`"N/A"`**.
- `summarize_task` añade campo `tokens` con `estimated` / `measured` / `mixed`, separando
  estimación (`len//4`) de medición (usage real). Verificable en la salida.

### 5. [BAJO] Tokens estimados etiquetados
`orchestrator.py` añade `_token_usage(prompt, code, verdict)`: usa `verdict["usage"]` del
provider si está disponible (`tok_source: "measured"`); si no, estima `len//4`
(`tok_source: "estimated"`). Cada intento lleva `tok_source`. `measure.py` lo agrega por
tarea. (Hoy ningún provider popula `usage` en el veredicto, así que todo se reporta como
`estimated` — el hook queda para cuando un provider reporte usage real.)

### 6. GAP DE TEST — `tests/test_orchestrator_cefl.py` (nuevo, OFFLINE)
Ejerce la feature CEFL end-to-end con `--provider stub` sobre el harness de
`examples/sandbox/loop_demo/` (contrato VÁLIDO que pasa `tc_lint`, no el BROKEN de
`test_lifecycle`), en un tempdir para no reescribir el fixture:
- (a) stub malo → intento 1 FAIL, stub bueno → intento 2 PASS; el target final contiene el
  código del stub bueno y la telemetría registra `best_candidate_index` y `best_complexity_score`.
- (b) todos fallan → resultado `ESCALATE` y `last_feedback` combina los fallos
  (`FAIL_ALL_CANDIDATES` + `candidates_evaluations`).
- Torneo: `get_complexity_score` incluye `function_length`; `_pick_best` desempata por índice
  de envío; menor score gana aunque su índice sea mayor; `_generate_candidates` preserva el
  orden de envío.

### `tests/test_measure.py` (nuevo)
- `api_saving_pct == "N/A"` cuando `passed==0`, y cuando stub PASS con tokens estimados.
- `api_saving_pct` numérico sólo con tokens `measured` + PASS.
- Campo `tokens` etiqueta `estimated` / `measured` / `mixed`.

## Nota de fuerza mayor: `examples/sandbox/loop_demo/task.md`
El demo del README no llegaba a E3: moría en `tc_lint` con `INVALID` porque al `task.md` (del
initial commit) le faltaba `test_command`, campo que se hizo obligatorio después (commits #34/#44).
Es un fixture stale del demo, no un archivo vedado. Se le agregó una línea:
`test_command: "python -m unittest test_decode_instruction.py"`. Sin esto, el demo es
imposible. Es la única edición fuera del allowlist estricto; reportada explícitamente.

## Demo del README (salida real)
`python runners/orchestrator.py examples/sandbox/loop_demo/task.md --provider stub --stub _stub_bad.py --stub _stub_good.py --max-attempts 3`
→ intento 1 FAIL (`all_candidates_failed`), intento 2 PASS (`stage: all`,
`best_complexity_score: 19`). `passed: 1`. (Antes: `INVALID` por lint; con E3 nunca pasaba.)

`measure.py` sobre el mismo lote: `api_saving_pct: "N/A"`, `tokens: "estimated"` (antes:
`100.0` falso).

## Suite
`python -m unittest discover -s tests -p "test_*.py"` — **399 tests, 0 failures, 0 errors**
(corrido dos veces, estable). Nota: durante la edición vi 2 fallos transitorios en
`test_purity_check` (tests anidados) que resultaron ser trabajo en curso de un dev paralelo
sobre `runners/purity_check.py` (lo vi pasar de `ast.walk` recursivo a `_walk_local`); no
eran míos y quedaron en verde al finalizar esa edición.

## Trade-offs
- **E3 eliminado, no desactivado**: opción recomendada por la auditoría (no aporta seguridad
  real). Consecuencia: si alguien confiaba en el "auditoría criptográfica E3" como señal, ya
  no existe — era una señal falsa.
- **Stub = 1 candidato por intento**: `_generate_candidates` consume exactamente UN stub por
  intento, sin importar `--candidates`. Esto es lo que hace que el demo produzca "intento 1
  FAIL, intento 2 PASS" y coincide con el help de `--stub` ("repetir por intento en orden").
  Consecuencia: la expansión paralela CEFL (N candidatos) no es ejercitable con stub — se
  ejercita con providers reales. Los tests unitarios cubren el torneo y el orden directamente.
- **`api_saving_pct` más conservativo**: hoy siempre es `"N/A"` porque ningún provider popula
  `usage` en el veredicto. Es honesto (separa estimado de medido) pero significa que la
  métrica numérica queda dormida hasta que un provider reporte usage real.