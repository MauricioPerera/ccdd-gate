# A3 — Servidor MCP — Auditoria

Area: A3 · Servidor MCP (`runners/complexity_mcp.py`, stdio JSON-RPC 2.0).
Modo: READ-ONLY. No se modificaron archivos fuente. Smoke corrido.

## Resumen

`complexity_mcp.py` expone 22 tools sobre stdio JSON-RPC. El sustrato determinista
(metricas, guardrails, lint, gates, audits) es **AST-puro**: las tools que reciben `code`
(`measure_complexity`, `scan_guardrails`, `scan_dependencies`, `check_*`) **no ejecutan ni
escriben** el codigo del anfitrion — solo lo parsean. Eso esta bien.

La afirmacion central del README — *"el servidor fija modelo y endpoint; el LLM anfitrion
solo pasa `task_path`"* — es **CIERTA** en el codigo (ver Hallazgo-2). No es mentira.

Pero hay **3 bugs de contencion de paths reales y reproducidos**, un **SSRF escondido en
`judge_audit`**, y un **manejo de errores JSON-RPC fragil que tira el servidor entero** con
un solo request malformado. Ninguno es RCE directa en el setup single-tenant (el anfitrion
ya tiene Bash/Write), pero fallan el principio de menor privilegio que un servidor MCP
deberia mantener frente al LLM, y dos de ellos serian escalada real en un deploy
hardened/CI donde el servidor corre con permisos distintos a los del agente.

Auto-dogfooding: el monolito de 56KB esta sorprendentemente bien descompuesto (50 funcs,
max cyclomatic=10, max nesting=3). **Solo 1 funcion excede el gate del propio proyecto**:
`run_ephemeral_agent` (46 lineas > max 41). El proyecto casi cumple su propio estandar.

Severidades (resumen):
- ALTO: `run_ephemeral_agent` escribe a `target` sin contencion (path traversal/absoluto → escritura arbitraria de contenido generado por el modelo remoto).
- ALTO: `request_human_attestation` no valida `agent` (path traversal → escritura de JSON a dir arbitrario).
- MEDIO: `judge_audit` acepta `api_url`/`provider` del llamador (ocultos del schema) → SSRF/exfiltracion de datos del eval al endpoint del atacante.
- MEDIO: JSON-RPC sin isolacion de errores; un payload malformado tira el server entero; `str(e)` se filtra al anfitrion; sin limite de payload.
- MEDIO: `run_integration_gate` / `run_ephemeral_agent` / `mutation_audit` ejecutan `test_command` del contrato sin contencion de path → command execution via contrato LLM-autoreado.
- BAJO: tools de audit (`root`) y `run_rules_gate` (`rules_path`,`root`) leen filesystem arbitrario (sin contencion, solo lectura).
- INFO: la inmutabilidad del endpoint del ejecutor depende solo del env del proceso spawn (sin allowlist, sin validacion de `api_url`); no es vulnerabilidad del LLM pero si del operador.

## Hallazgos

### [SEV: ALTO] run_ephemeral_agent: `target` se resuelve sin contencion → escritura arbitraria
- Archivo: `runners/complexity_mcp.py:704`, escritura en `:801` y `:803`/`:879`, restauracion en `:894`
- Descripcion: `_prepare_ephemeral_task` hace `target = tp.parent / fm["target"]`. `fm["target"]`
  viene del front-matter del contrato, que **autorea el LLM anfitrion**. No hay contencion
  (a diferencia de `lint_task_contract`, que SI valida `relative_to` en `:510-513`). Un `target`
  absoluto o con `..` escapa al directorio del contrato. Luego `run_ephemeral_agent` **escribe**
  el codigo generado por el modelo remoto en ese path (`_apply_new_code`, `:798-803`), y solo
  restaura el original si agota las 3 iteraciones (`:894`).
- Impacto: primitive de **escritura arbitraria** (dentro de los permisos del proceso) de
  contenido producido por el small-executor remoto, a un path elegido por el anfitrion. En un
  deploy donde el servidor MCP corre con permisos distintos al del agente (servicio, contenedor,
  CI), esto es escalada. En el setup single-user dev, el anfitrion ya tiene `Write` → no es
  capacidad nueva, pero es un fallo de defense-in-depth: el servidor deberia negarse a escribir
  fuera del arbol del contrato.
- Repro (real, lectura demostrada — la escritura sigue el mismo path):
  ```
  contract target: C:\Windows\win.ini   (absoluto)
  > ctx, err = m._prepare_ephemeral_task({'task_path': contract})
  > ctx['target'].resolve() -> C:\Windows\win.ini
  > ctx['original_source'][:80] -> '; for 16-bit app support\n[fonts]\n[extensions]...'
  ==> escape confirmado: target leido de path absoluto fuera del contract dir
  ```
  La misma `ctx['target']` es la que `_apply_new_code` sobrescribe con salida del LLM.
- Fix sugerido: validar `target.resolve().relative_to(tp.parent.resolve())` y rechazar
  absolutos/`..` (igual que `lint_task_contract` hace con `test_code`). Aplicar lo mismo a
  `tests` y a `test_cwd` en `task_gate` (`runners/task_gate.py:58-62`).

### [SEV: ALTO] request_human_attestation: `agent` no validado → path traversal write
- Archivo: `runners/complexity_mcp.py:560` y `:573-583`
- Descripcion: la funcion toma `agent = args.get("agent", DEFAULT_AGENT)` **sin validarlo contra
  `AGENTS`**, y luego arma `out_dir = CONTRACTS / agent / "pending_attestations"` y escribe
  `<hash>.json` ahi. El schema declara `enum` para `agent` (`:280`), pero el servidor **no lo
  re-valida** (el enum es solo un hint para el cliente; un request JSON-RPC crudo lo bypassa).
  `complexity_rubric` y `scan_guardrails` SI validan via `_agent_dir` (`:407-409`); esta tool no.
- Impacto: escritura de un archivo `.json` (contenido: `code`+`reason` controlados por el
  llamador, filename = sha256 del `code`) a un directorio arbitrario resuelto desde `CONTRACTS`.
  El filename esta fijado por el hash (no totalmente libre), pero el **directorio** es
  controlable y `mkdir(parents=True, exist_ok=True)` lo crea.
- Repro (real, limpiado):
  ```
  > m.request_human_attestation({'code':'x=1','reason':'r','agent':'../../_audit_probe'})
  -> {"status": "Atestación solicitada", "hash": "03987480..."}
  > would-write dir: D:\repos\Nueva carpeta (38)\_audit_probe\pending_attestations  (FUERA de contracts/)
  > exists: True   (archivo creado, luego limpiado a mano)
  ```
- Fix sugerido: usar `_agent_dir(args.get("agent", DEFAULT_AGENT))` como las demas, o validar
  `agent in AGENTS` antes de armar el path; rechazar cualquier valor fuera del enum.

### [SEV: MEDIO] judge_audit acepta `api_url`/`provider` del llamador (ocultos del schema) → SSRF
- Archivo: `runners/complexity_mcp.py:922` (`judge_audit`), schema en `:314-315`
- Descripcion: el schema de `judge_audit` solo declara `eval_path`. Pero el handler lee
  `provider=args.get("provider","stub")` y `api_url=args.get("api_url","")` y los pasa a
  `judge_audit.audit` (`:922`), que a su vez los pasa a `eval_judge.judge` para hacer llamadas
  LLM al juez Tier 2. Un anfitrion que envie campos extra (la mayoria de clientes pasa todo el
  dict) puede redirigir las llamadas del juez a un endpoint arbitrario, enviandole los prompts,
  casos del dataset y output del agente.
- Impacto: SSRF + exfiltracion de datos del eval-contract a un URL controlado por el llamador.
  Por defecto `provider="stub"` (offline, determinista) → no se dispara salvo que el llamador
  inyecte `provider` != stub + `api_url`. Contradice el patron "el servidor decide el endpoint"
  que el proyecto aplica en `run_ephemeral_agent`.
- Repro: no ejecutado contra un endpoint real (no hay servidor LLM remoto en este audit);
  la lectura del codigo confirma el passthrough: `judge_audit.audit(path, provider=args.get(...), api_url=args.get(...))`.
- Fix sugerido: o bien sacar `api_url`/`provider` de la superficie (fijarlos por env/contrato,
  como el ejecutor), o declararlos explicitamente en el schema y validar `api_url` contra un
  allowlist. Como minimo, ignorar `api_url` cuando `provider=="stub"`.

### [SEV: MEDIO] JSON-RPC fragil: un request malformado tira el servidor entero
- Archivo: `runners/complexity_mcp.py:1038-1042` (`main`), `:1010-1018` (`handle_tools_call`), `:1022-1035` (`handle`)
- Descripcion: `main()` hace `handle(json.loads(line))` **sin try/except**. Cualquier excepcion
  —`JSONDecodeError`, `KeyError`, `AttributeError`— propaga y mata el proceso servidor entero.
  Ademas `handle_tools_call` lee `params["name"]` (`:1011`) **fuera** del try/except (`:1015-1018`),
  y `handle` lee `msg["params"]` (`:1032`) sin `.get`. No hay validacion de `jsonrpc=="2.0"`, ni
  del tipo de `id`, ni soporte de batch (un array → `AttributeError`).
- Impacto: DoS de un solo mensaje: cualquier cliente (o el propio anfitrion con un tool-call
  malformado) tiraria el servidor MCP y habria que re-spawnearlo. No hay tamano maximo de payload
  (una linea de GBs → `json.loads` llena memoria). Las respuestas de error ponen `str(e)` en el
  texto (`:1018`): pueden filtrar rutas (p.ej. `Task file no encontrado: <path>`, `Error
  conectando al LLM: <url>`) al anfitrion — no stack trace completo, pero si informacion sensible.
- Repro (real):
  ```
  no-name        (tools/call sin name)   -> CRASH: KeyError "'name'"
  no-params      (tools/call sin params) -> CRASH: KeyError "'params'"
  batch-array    ([{...initialize}])     -> CRASH: AttributeError "'list' object has no attribute 'get'"
  non-dict       ("hello")               -> CRASH: AttributeError "'str' object has no attribute 'get'"
  malformed-json ('xxx')                 -> CRASH: JSONDecodeError  (en json.loads, main, sin handler)
  ```
- Fix sugerido: envolver cada `handle()` en try/except que devuelva un error JSON-RPC `-32700`/
  `-32600` y **no** mate el loop; validar `jsonrpc=="2.0"` y tipo de `id`; usar `params.get`
  y validar `name` antes de dispatch; cap de tamano por linea; no filtrar `str(e)` (mapear a
  mensajes genericos, loguear detalle a stderr).

### [SEV: MEDIO] test_command del contrato se ejecuta sin contencion de path
- Archivo: `runners/task_gate.py:69-79` (gate1), `:160-171` (integration); invocado por
  `runners/complexity_mcp.py:554` (`run_integration_gate`), `:881` (`run_ephemeral_agent` via
  subprocess), `:544` (`mutation_audit`)
- Descripcion: `task_gate` corre `subprocess.run(shlex.split(fm["test_command"]), cwd=...)` sin
  shell (bien, evita inyeccion de shell), pero **el comando mismo** viene del front-matter del
  contrato, que el anfitrion autorea. `run_integration_gate`/`run_ephemeral_agent` aceptan
  `task_path` arbitrario (sin contencion) → el anfitrion puede apuntar a un contrato que el
  mismo escribio con un `test_command` malicioso y dispararlo. Lo mismo `mutation_audit` y
  `run_eval_gate`/`judge_audit` con sus paths.
- Impacto: command execution via contrato LLM-autoreado. En single-tenant el anfitrion ya tiene
  Bash → no es capacidad nueva; en deploy hardened/CI donde el servidor MCP corre aislado del
  agente, si lo es. Ademas `run_integration_gate` no restringe `task_path` → lectura de
  cualquier `.md` del filesystem que el proceso pueda leer.
- Repro: no ejecutado (evitar correr comandos arbitrarios en el audit). La lectura del codigo
  confirma `subprocess.run(shlex.split(test_cmd_str), ...)` con `test_cmd_str` del contrato.
- Fix sugerido: contener `task_path` al repo (o a un allowlist de dirs de contratos); considerar
  un allowlist de comandos validos para `test_command` (p.ej. solo `python -m pytest <tests>`).

### [SEV: BAJO] Tools de audit y run_rules_gate aceptan `root`/`rules_path` arbitrario (lectura)
- Archivo: `runners/complexity_mcp.py:523-538` (`audit_composition`/`orphan_targets`/`annotations`),
  `:967-973` (`run_rules_gate`)
- Descripcion: estas tools pasan `args.get("root") or "."` y `rules_path` directamente a los
  modulos de audit, que caminan el filesystem. Sin contencion → el anfitrion puede apuntar a
  cualquier directorio y mapear/leer archivos del proyecto (`.py`, yaml, etc.) que el proceso
  pueda leer.
- Impacto: solo lectura; escalada de lectura si el servidor tiene acceso a paths que el agente
  no. No escritura ni ejecucion.
- Fix sugerido: contener `root`/`rules_path` al working dir o a un allowlist.

### [SEV: INFO] Inmutabilidad del endpoint del ejecutor depende solo del env del spawn
- Archivo: `runners/complexity_mcp.py:38-39` (defaults), `:712-715` (uso), README `:167`
- Descripcion: `DEFAULT_EXECUTOR_MODEL`/`DEFAULT_EXECUTOR_API` se leen de `os.environ` **al
  importar el modulo** (`:38-39`). El servidor MCP lo spawnea el harness del anfitrion segun
  `.mcp.json`. Quien controle el env de ese proceso (operador via `.mcp.json` env / shell)
  controla el modelo y el endpoint. No hay allowlist ni validacion de `api_url` (puede ser
  externo). El LLM anfitrion **no** tiene una tool para mutar el env del servidor ni
  re-spawnearlo → la afirmacion del README ("el LLM no elige el modelo") se cumple. Pero el
  boundaries recae en el operador, no en enforcement del servidor.
- Impacto: si el operador apunta `CCDD_EXECUTOR_API` a un endpoint externo/hostil, todo
  `code + contrato + tests + fuente del target` del anfitrion se envia ahi. Es decision del
  operador, no vulnerabilidad del LLM.
- Fix sugerido (defense-in-depth): validar que `api_url` sea `localhost`/`127.0.0.1` por defecto
  y requerir opt-in explicito para endpoints externos; documentar el riesgo de exfiltracion.

## Auto-dogfooding (metricas de complexity_mcp.py sobre su propio gate)

Corrido `metrics_backends.get_backend('python').measure(code)` sobre el propio
`complexity_mcp.py` (1047 lineas, ~56KB). 50 funciones.

Umbrales del proyecto (`contracts/complexity-agent/thresholds.txt` + `mb.RED`):
cyclomatic rojo 11 / critico >20 · nesting rojo 4 / critico ≥5 · lines rojo 41-80 / critico >80 ·
params rojo ≥6.

| metrica | max encontrado | umbral rojo | excede? |
|---|---|---|---|
| cyclomatic | 10 | 11 | NO |
| nesting | 3 | 4 | NO |
| params | 6 (en `_apply_new_code`) | 6 | limite justo, no excede |
| lines | 46 (`run_ephemeral_agent`) | 41 | **SI** |

**Unica funcion over-budget**: `run_ephemeral_agent` (`:851`, 46 lineas > 41). Esta justo sobre
el umbral rojo (zona "MEDIA" del contrato). Todas las demas pasan. El monolito de 56KB esta
**mucho mejor descompuesto de lo que su tamano sugiere**: el autor uso tecnicas explicitas
para aplanar (guard clauses, `_BraceScanner` con consumidores separados, helpers `_stage_*`).
El proyecto **cumple su propio estandar** salvo 1 funcion que excede por 5 lineas.

Notas: `mb.RED` usa `function_length=41`; el contrato marca 41-80 como rojo "MEDIA". Ninguna
funcion esta en zona critica. El parametro_count=6 de `_apply_new_code` esta exactamente en el
limite (rojo ≥6) — seria un finding justo en un gate estricto.

## Cosas que estan BIEN

- **Afirmacion del README verificada como CIERTA**: `run_ephemeral_agent` solo acepta
  `task_path` en el schema (`:287-289`); `_prepare_ephemeral_task` **ignora** cualquier
  `model`/`api_url` que venga en args y usa `DEFAULT_EXECUTOR_MODEL`/`DEFAULT_EXECUTOR_API`
  (`:712-715`). Tests lo congelan (`tests/test_mcp_instructions.py:55-62`,
  `:40-46`). El LLM anfitrion **no** puede inyectar modelo/endpoint via la tool.
- **Tools de `code` son seguras**: `measure_complexity`, `scan_guardrails`,
  `scan_dependencies`, `check_signature/purity/mutable_defaults/bare_except/asserts/none_cmp`
  solo hacen AST parse / regex sobre el string — no ejecutan ni escriben el codigo del
  anfitrion. No hay `eval`/`exec` del input.
- **`lint_task_contract` SI contiene el path** de `test_code` (`:510-513`): valida
  `relative_to(tempdir)` y cae al basename si escapa. Es el modelo a seguir para las demas.
- **Smoke pasa**: `initialize` → `tools/list` (22 tools) → `measure_complexity` /
  `complexity_rubric` / `scan_guardrails` (detecta `no-secrets`) / `lint_task_contract`
  (contrato roto → ok=False, 19 errors). El protocolo MCP funciona end-to-end.
- **`run_integration_gate` da el MISMO veredicto que la CLI** `task_gate.py`: ambos llaman a
  `task_gate.gate(path)` (`complexity_mcp.py:554` vs `task_gate.py:455`). Sin divergencia para
  contratos existentes. (Divergencia menor: el wrapper MCP pre-chequea `Path(path).exists()` y
  devuelve un INVALID propio `:553` antes de `gate()`; la CLI deja que `gate()` maneje el
  missing-file. Mismo veredicto, shape ligeramente distinto para el caso missing.)
- **`run_ephemeral_agent` invoca la CLI** `task_gate.py` como subprocess (`:881`) → veredicto
  identico al CLI.
- **Separacion stdout/stderr**: los prints de debug del LLM output van a stderr (`:878`),
  stdout se reserva para JSON-RPC. No corrompe el protocolo.
- **Restauracion del target** on FAIL (`:894`) — intenta no dejar el archivo roto. (Pero ver
  Hallazgo-1: si el target es absoluto/escapado, la restauracion tambien toca ese path.)
- **`_BraceScanner`** (`:591-673`): complejidad intencionalmente aplanada con consumidores por
  modo — buen dogfooding del propio gate de anidamiento.

## Limitaciones de mi auditoria

- **No corri `run_ephemeral_agent` contra un LLM real** (no hay endpoint `qwen3-coder` disponible
  en este entorno). El Hallazgo-1 (escritura arbitraria) se demostro hasta la **resolucion del
  path + lectura** del target via `_prepare_ephemeral_task`; la **escritura** sigue el mismo
  `ctx['target']` (`_apply_new_code`, `:798-803`) pero no se ejecuto un ciclo completo para no
  sobrescribir archivos. La cadena lectura→escritura es directa en el codigo.
- **No probe SSRF de `judge_audit` contra un endpoint real** (Hallazgo-3): confirmado por lectura
  de codigo (passthrough de `api_url` al handler `:922` y a `eval_judge.judge`). No reproduje
  trafico.
- **No ejecute `test_command` malicioso** (Hallazgo-5): confirmado por lectura de
  `task_gate.py:69-79`; evite correr comandos arbitrarios durante el audit.
- **Path traversal de `request_human_attestation` (Hallazgo-2)**: reproducido y limpiado a mano
  (archivo creado en `D:\repos\Nueva carpeta (38)\_audit_probe\pending_attestations\`, luego
  borrado). No quedo artefacto en el repo.
- **No audite** a fondo los modulos importados (`task_gate.py`, `eval_gate.py`, `judge_audit.py`,
  `audit_*.py`, `mutation_audit.py`) mas alla de lo necesario para confirmar los hallazgos; su
  logica interna (p.ej. si `mutation_audit` ejecuta tests de forma contenida) queda para una
  auditoria dedicada de esos runners.
- **Threat model asumido**: single-tenant dev (anfitrion con Bash/Write) vs deploy hardened/CI.
  Las severidades ALTO se basan en el segundo; en el primero varias redundan con capacidades que
  el agente ya tiene. Lo dejo explicito por hallazgo para que el operador decida.
- **No se modifico ningun archivo fuente**. El unico archivo escrito es este reporte
  (`audit/A3-mcp.md`). No se metieron archivos de prueba en el repo.