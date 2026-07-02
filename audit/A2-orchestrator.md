# A2 — Orquestador y ejecutor — Auditoria

## Resumen

Auditoría READ-ONLY del orquestador (`runners/orchestrator.py`), ejecutor efímero (`runners/complexity_mcp.py::run_ephemeral_agent`), `run_executor.py`, `runners/measure.py` y los runners pre/post-complexity. Verifiqué ejecutando el demo stub en una **copia en temp** (no toqué el repo) y aislando causas con snippets.

**Resultado principal:**

1. **CRÍTICO — ejecución de código del modelo en el host sin aislamiento.** Confirmado y precisado. El README lo admite (línea 362); el riesgo es mayor que la admisión: el código se escribe en el **target real del repo** y los tests lo importan con `cwd = carpeta del target`, o sea en el árbol real del usuario, no en un sandbox.
2. **ALTO — la demo stub documentada en el README está rota de dos formas** (reproducido): el contrato ejemplo no tiene `test_command` → `INVALID` (exit 2); y aun arreglando eso, el gate “E3 Entropía” rechaza todo candidato stub porque el nonce es aleatorio por intento y el stub no puede incluirlo → `ESCALATE` (exit 1).
3. **ALTO — el gate E3 “auditoría criptográfica” es security theater.** El nonce se le dicta al modelo en el mismo prompt donde se le pide que lo copie. Cero valor criptográfico; sólo rompe el provider determinista.
4. **MEDIO — `measure.py` reporta 100 % de ahorro sobre una corrida FALLIDA sin llamadas API reales** (reproducido).
5. **MEDIO — torneo CEFL no determinista en empates** (reproducido el reorder vía `as_completed`); contradice “idéntico corrida a corrida”.
6. **MEDIO — escrituras no atómicas al target real + sin manejo de excepciones por candidato**: un error de red cae el proceso y deja el archivo del usuario con código roto/parcial.

Lo que está **bien**: sin `shell=True` (shlex.split), el modelo/endpoint del efímero lo fija el servidor (no inyectable por el LLM que llama), no se loguean API keys, el gate es determinista y E3 sólo degrada PASS→FAIL (nunca genera PASS falso).

---

## Hallazgos

### [SEV: CRITICO] Ejecución de código generado por el modelo en el host, sin aislamiento, sobre el repo real
- Archivo: `runners/orchestrator.py:119,145,161`; `runners/task_gate.py:66-85`; `runners/complexity_mcp.py:879,881`; `README.md:362-363`
- Descripción: El loop escribe el código que devuelve el modelo **directamente en el archivo target del usuario** (`target.write_text(code)`), luego `run_gate` invoca `task_gate.py` que corre `test_command` con `cwd = target.parent` (la carpeta real del proyecto). Los property-tests hacen `from <target> import <fn>`, así que el módulo del modelo se ejecuta **a nivel de módulo, con los privilegios del proceso, en el directorio real del repo**, antes de cualquier veredicto. El ejecutor efímero MCP hace lo mismo (`_apply_new_code` → `target.write_text` → `subprocess.run task_gate`).
- Impacto: Código arbitrario del modelo pequeño (o de un contrato envenenado) logra **ejecución arbitraria en el host en el momento del import**: leer/escribir/borrar archivos del repo y del usuario, exfiltrar por red, persistir, etc. El gate **no** contiene esto; lo da por sentado. El README lo admite (“para correr código ajeno usá un sandbox aislado, no el host”) pero la precisión que falta es que **ni siquiera el target está aislado**: se muta el archivo real del usuario y se ejecuta contra el árbol real. No hay tempdir, no hay contenedor, no hay red-kill, no hay fs-readonly. Comparar con `lint_task_contract` (complexity_mcp.py:502) que sí usa `tempfile.TemporaryDirectory()` — el loop de implementación no.
- Repro: `cp -r examples/sandbox/loop_demo $TEMP/ccdd_a2_demo` (con `test_command` añadido), correr el orchestrator stub: el gate importa y ejecuta `disassembler.py` escrito por el “modelo”. Salida real: el gate corre `python -m unittest test_decode_instruction.py` que hace `from disassembler import decode_instruction` — ejecución confirmada en el host (ver cualquier `gate1-tests` output del repro abajo).
- Fix sugerido: Correr el target+tests dentro de un contenedor desechable (sin red, FS del repo read-only, cwd en un tempdir con copia del target), o al menos escribir el candidato en un tempdir y apuntar `test_cwd` ahí. Nunca escribir en el target real hasta tener PASS, y entonces con `os.replace` atómico. Documentar el riesgo en el encabezado del orchestrator, no sólo en el README.

### [SEV: ALTO] El gate “E3 Entropía / auditoría criptográfica” es security theater y rompe el provider stub
- Archivo: `runners/orchestrator.py:60-67,107-112,138-139,109`; `runners/complexity_mcp.py:38-39` (no afecta al efímero, sólo al orchestrator)
- Descripción: Por cada intento se genera `nonce = secrets.token_hex(16)`, se imprime `SHA256={hash[:16]}...` con la leyenda “Generando commit” / “auditoría criptográfica E3”, y `build_prompt` **le dicta al modelo** la línea exacta `# E3_NONCE: {nonce}` que debe incluir. Luego `_e3_verdict` sólo verifica que el substring esté presente. No hay compromiso previo, no hay firma, no hay verificación de autoría: el modelo recibe el nonce y la orden de copiarlo en el mismo prompt. Cualquier modelo que siga instrucciones pasa; el provider `stub` (archivos pre-autorados deterministas) **no puede** incluir un nonce aleatorio por intento, así que todo candidato stub que pasaría el gate es degradado a `FAIL stage=gate3-entropy`.
- Impacto: (a) Cero valor de seguridad — es un eco de compliance disfrazado de criptografía. (b) Incompatibilidad total con el modo `stub`, que es el único modo offline/determinista para demostrar la mecánica del loop. (c) Mensaje engañoso (“SHA256”, “commit”, “auditoría criptográfica”) que sobre-vende una proteccion inexistente.
- Repro (en copia temp del demo, con `test_command` añadido):
  ```
  E3 verdict on good code WITHOUT nonce: {'verdict': 'FAIL', 'stage': 'gate3-entropy', ...}
  E3 verdict on good code WITH nonce:    {'verdict': 'PASS', 'stage': 'all'}
  ```
  El `task_gate.py` directo sobre el `_stub_good.py` da `PASS` (cyclomatic 6 ≤ 8, etc.); el orchestrator con el mismo stub da `ESCALATE` porque E3 lo degrada.
- Fix sugerido: Eliminar E3 o, si se quiere una prueba de “el modelo generó esto”, usar un esquema real (commit-then-reveal con hash publicado ANTES de pedir el código, o firma del servidor sobre el código). Como mínimo, **desactivar E3 para `provider == "stub"`** para no romper el demo determinista, y dejar de llamarlo “criptográfico”.

### [SEV: ALTO] La demo stub documentada en el README no corre (exit 2)
- Archivo: `examples/sandbox/loop_demo/task.md:10-13`; `README.md:228-231` (comando documentado); `runners/tc_lint.py` (regla `tc-test-command`)
- Descripción: El comando del README
  `python runners/orchestrator.py examples/sandbox/loop_demo/task.md --provider stub --stub .../_stub_bad.py --stub .../_stub_good.py --max-attempts 3`
  produce `INVALID` (exit 2) porque el contrato ejemplo **no declara `test_command`** (campo requerido por `tc_lint`). Ni siquiera llega al loop.
- Repro (sobre el repo real, sin modificar nada):
  ```
  $ python runners/orchestrator.py examples/sandbox/loop_demo/task.md --provider stub --stub .../_stub_bad.py --stub .../_stub_good.py --max-attempts 3
  Exit code 2
  {"total":1,"passed":0,"results":[{"task":"task.md","result":"INVALID","attempts":0}]}
  ```
  `tc_lint` sobre el contrato: 3 errores, `'test_command' is a required property`.
- Impacto: La primera experiencia documentada de un usuario nuevo está rota. Además, al arreglarla (añadir `test_command`) choca con el hallazgo anterior (E3 → `ESCALATE`). La mecánica CEFL “fail → retry → pass” **no es demostrable** con los archivos del repo tal cual.
- Fix sugerido: Añadir `test_command: "python -m unittest test_decode_instruction.py"` (y `test_cwd: "."`) al contrato ejemplo, y resolver E3 para stub. Verificar el comando del README en CI.

### [SEV: MEDIO] `measure.py` puede mentir sobre el ahorro: 100 % saving en una corrida FALLIDA sin llamadas API
- Archivo: `runners/measure.py:22,46,88`; `runners/orchestrator.py:156`
- Descripción: `PRICE = {"big_in":15,"big_out":75,"small_in":0,"small_out":0}` (pequeño local = 0 por diseño). `summarize_task` calcula `ours` con precio `small` (0) y `big_loop` con precio `big` sobre los **mismos tokens estimados** (`in_tok=len(prompt)//4`, `out_tok=len(code)//4`) más `loops*REVIEW_OUT_PER_LOOP` (300, constante placeholder). Con `--provider stub` no hay ninguna llamada API real, pero los “tokens” se siguen estimando y precio-big para el loop de comparación → `ours_usd=0`, `big_loop_usd>0`, `api_saving_pct=100.0` **aunque `passed=0` y `result=ESCALATE`**.
- Impacto: El harness reporta ahorro perfecto sobre un fracaso. El docstring es honesto (“sin pretensión estadística”), pero el número que escupe es estructuralmente inflable y se muestra sin la salvedad en el `totals`. Alguien que corra `measure.py` con stub se lleva “100 % de ahorro” sin haber gastado nada ni haber pasado nada.
- Repro (copia temp del demo, con `test_command`):
  ```
  "totals": {"tasks":1,"passed":0,"escalations":0,"gate_runs_at_0_tokens":3,
             "ours_usd":0.0,"big_loop_usd":0.0675,"api_saving_pct":100.0}
  ```
- Fix sugerido: No emitir `api_saving_pct` cuando `passed==0` o cuando no hubo llamadas API reales (stub). Separar “tokens estimados” de “tokens medidos” y etiquetarlos. Hacer `REVIEW_OUT_PER_LOOP` y el doble-input del big-loop configurables y explícitos en la salida.

### [SEV: MEDIO] Torneo CEFL no determinista en empates (rompe “idéntico corrida a corrida”)
- Archivo: `runners/orchestrator.py:101-104,150-151`
- Descripción: `_generate_candidates` recoge los futures con `concurrent.futures.as_completed`, que **devuelve en orden de finalización**, no de envío. `passed_candidates.sort(key=get_complexity_score)` es un sort **estable**, así que ante un empate de complejidad gana el candidato que **terminó primero** la red. Con latencia de red variable, el ganador cambia entre corridas idénticas.
- Impacto: La promesa documental “idéntico corrida a corrida” (orchestrator.py:11) se rompe para el tie-break del torneo. Dos corridas con el mismo prompt y semilla pueden congelar candidatos distintos.
- Repro (el reorder es real, la no-determinismo depende del jitter de red):
  ```
  submission order: [TAG:5, TAG:1, TAG:3]  (latencias 5,1,3)
  as_completed order across 3 trials: ['TAG:1','TAG:3','TAG:5']  (por tiempo, no por envío)
  ```
  Con `provider != "stub"` y `candidates>1`, el orden de `candidates_code` es el de completion.
- Fix sugerido: Ordenar los candidatos por `index` (orden de envío) antes del tie-break, o desempatar por `index` explícito (`sort(key=(score, index))`) para hacer el ganador determinista.

### [SEV: MEDIO] Escrituras no atómicas al target real + sin manejo de excepciones por candidato
- Archivo: `runners/orchestrator.py:104,119,145,161`; `runners/complexity_mcp.py:879-880`
- Descripción: `target.write_text(code)` escribe **in-place** sobre el archivo real del usuario (sin temp+`os.replace`). `run_rounds` no envuelve `_generate_candidates`/`_evaluate_candidates` en try/except. Si `fut.result()` propaga una excepción de red (urlopen raise), o si `call_llm` lanza, el proceso cae **sin** ejecutar `target.write_text(original_target_code)` (la restauración sólo ocurre al final de una ronda fallida completa). El target queda con el código del último candidato escrito, posiblemente roto o parcial.
- Impacto: Una interrupción (Ctrl-C, crash de red, OOM) a mitad de `_evaluate_candidates` deja el archivo del usuario corrupto, sin rollback. No hay write atómico → un crash a mitad de `write_text` deja el archivo truncado.
- (Sospecha confirmada por lectura + principios; no reproduje el crash por no tener endpoint real.)
- Fix sugerido: Escribir a un temp y `os.replace` al target sólo tras PASS (atómico). Envolver la ronda en try/except que siempre restore `original_target_code` en cualquier salida, incluida excepción.

### [SEV: MEDIO] Providers: sin reintentos, timeouts heterogéneos, errores de red mal manejados
- Archivo: `runners/complexity_runner.py:64,84,91`; `runners/pre_complexity_runner.py:67`; `runners/complexity_mcp.py:780,867-875`
- Descripción: ollama `timeout=600`, openai `timeout=900`, anthropic sin timeout explícito (default SDK). **Ningún provider reintenta.** Un error transitorio (HTTP 5xx, reset de conexión) lanza y, en el orchestrator, propaga sin cleanup (ver hallazgo anterior). En el efímero, `_stream_completion` devuelve `("", True, None)` en `socket.timeout`; si llegó `partial_content`, el `continue` **consume una de las 3 iteraciones** del gate lógico.
- Impacto: (a) Cuelgue posible hasta 900s sin cancelación. (b) Un modelo que stream-ea lento pero válido puede agotar `max_iterations=3` en timeouts y devolver `FAIL` sin haber recibido un veredicto real del gate (FAIL falso por timeout, no por código). (c) Un 5xx transitorio mata la corrida sin reintento.
- Fix sugerido: Timeouts configurables y uniformes, retry con backoff para 5xx/conn-reset, y **no** contar un timeout-continue como iteración de gate (o reintentar el mismo intento sin decrementar).

### [SEV: BAJO] Tokens estimados como `len//4`, no reales
- Archivo: `runners/orchestrator.py:156`
- Descripción: `in_tok: len(prompt)//4, out_tok: len(code)//4`. Aproximación tosca de char→token; sesgada para español/CJK (más tokens/char). measure.py construye el costo sobre estos.
- Impacto: Cifras de costo imprecisas (no placeholders puros, pero no medidos).
- Fix sugerido: Usar el `usage` real que devuelven los providers cuando esté disponible; mantener `len//4` sólo como fallback etiquetado “estimado”.

### [SEV: BAJO] Provider `openai` hardcodea `Authorization: Bearer local`
- Archivo: `runners/complexity_runner.py:82`
- Descripción: El header de auth es siempre `Bearer local`, sin leer `OPENAI_API_KEY`. Asumido para LM Studio/vLLM locales. Contra OpenAI real no autentica.
- Impacto: Sorpresa para quien apunte `OPENAI_BASE_URL` a OpenAI real esperando que use su key.
- Fix sugerido: `Authorization: Bearer ${os.environ.get("OPENAI_API_KEY","local")}`.

### [SEV: BAJO] Scripts legacy/stale: `run_executor.py` y `smoke_run_ephemeral_agent.py`
- Archivo: `run_executor.py:44,67,70`; `scripts/smoke_run_ephemeral_agent.py:7-11,48-51`
- Descripción: `run_executor.py` (raíz) es single-shot contra `localhost:1234`, **escribe el código del modelo al target real antes de gatear** (sin loop, sin validación previa) y luego corre el gate; sin `encoding=` en el subprocess (Windows-locale). `smoke_run_ephemeral_agent.py` pasa `model`/`api_url` en `args` a `run_ephemeral_agent`, que **los ignora** (complexity_mcp.py:712-715 fija el del servidor) — el smoke está stale y puede confundir sobre qué decide el modelo.
- Impacto: Confusión + mismo riesgo de host-execution que el orchestrator, sin la disciplina del loop.
- Fix sugerido: Borrar o marcar `run_executor.py` como legacy; alinear el smoke con la firma real (sólo `task_path`).

### [SEV: BAJO] `get_complexity_score` ignora `function_length`
- Archivo: `runners/orchestrator.py:90-93`
- Descripción: El score de torneo suma `cyclomatic + nesting_depth + parameter_count` pero **no** `function_length`, aunque es una métrica que el gate mide y el budget incluye (`lines_max`).
- Impacto: Empates/orden del torneo no reflejan longitud; dos funciones con igual cyclo/nesting/params pero muy distinta longitud puntúan igual.
- Fix sugerido: Incluir `function_length` en el score o documentar por qué se excluye.

---

## Cosas que están BIEN

- **Sin `shell=True` en ningún sitio.** `task_gate.py:73,171` usa `shlex.split(test_command)` + `subprocess.run` sin shell, igual `orchestrator.run_gate:72` y `complexity_mcp.run_ephemeral_agent:881`. No hay inyección de shell vía nombre de test/target/path. El comentario de task_gate.py:70-72 lo razona bien (cmd.exe rompe comillas simples en Windows).
- **El modelo/endpoint del ejecutor efímero lo fija el servidor, no el llamador.** `complexity_mcp.py:38-39,712-715` ignora cualquier `model`/`api_url` que venga en `args`; el operador sólo puede cambiarlo por env (`CCDD_EXECUTOR_MODEL`/`CCDD_EXECUTOR_API`). El LLM anfitrión no puede inyectar el implementador. Confirmado.
- **No se loguean API keys.** Los `print` van del output del modelo/prompt/feedback, no de credenciales. `anthropic.Anthropic()` lee la key de env sin eco.
- **El gate es determinista y el LLM no decide el verdicto.** `task_gate.gate` es AST puro; E3 sólo **degrada** PASS→FAIL (`_e3_verdict`), nunca eleva FAIL→PASS → no puede generar un PASS falso por sí mismo.
- **Restauración del target tras ronda fallida completa** (`orchestrator.py:144,161`) y tras fallo total del efímero (`complexity_mcp.py:894`).
- **`lint_task_contract` usa `tempfile.TemporaryDirectory()`** (limpio) con protección path-traversal (`complexity_mcp.py:511-513`): una ruta `..`/absoluta cae al basename dentro del tempdir.
- **Desambiguación de funciones homónimas por `target_line`** (`task_gate.py:93-110`) — evita medir la def equivocada y dar PASS engañoso (issue #41 documentado in-code).

---

## Limitaciones de mi auditoria

- **No tenía un endpoint LLM real** (ollama/openai/anthropic) durante la auditoría. Los hallazgos de providers (timeouts, reintentos, manejo de errores) son por lectura + principios; **no reproduje** un crash de red real ni el cuelgue de 900s. El comportamiento network lo marco como confirmado-por-lectura, no reproducido.
- **El torneo no determinista**: reproduje que `as_completed` reordena por tiempo (real), pero la no-determinismo **run-to-run** depende del jitter de red real, que no ejercité. Es consecuencia directa del reorder reproducido + sort estable.
- **El demo stub lo reproduje en una copia en `$TEMP`** con `test_command` añadido, porque el contrato del repo no lo tiene y soy READ-ONLY sobre el repo. No modifiqué ningún archivo fuente.
- **No audité a fondo** `ccdd.py`, `metrics_backends.py`, `runner_common.py`, `eval_gate.py`, `mutation_audit.py` ni el esquema JSON de contratos — fuera del área A2.
- **No medí** el comportamiento del efímero con el provider `stub` (no expuesto ahí) ni el path de `run_integration_gate` sobre grupos recursivos profundos.
- `run_executor.py` y `smoke_run_ephemeral_agent.py` los revisé por lectura; no los ejecuté (requieren LM Studio local).