# RA2 — Reparación de los 4 hallazgos de seguridad en `runners/complexity_mcp.py`

Rama: `audit-repairs`. Archivo tocado: `runners/complexity_mcp.py` (aislado; no se tocó
`task_gate.py`, `deps_check.py`, `orchestrator.py`, `measure.py` ni ningún otro check).

## Hallazgos arreglados

### 1. [ALTO] Path traversal en `request_human_attestation`
`agent = args.get("agent", DEFAULT_AGENT)` se usaba sin validar para construir
`CONTRACTS / agent / "pending_attestations"` y escribir un `.json`. Un `agent="../../x"`
escapaba de `contracts/`.

**Fix:** guard temprano `if agent not in AGENTS: return {"error": ...}` antes de armar el
path; luego `_agent_dir(agent)` (que ya usan `complexity_rubric`/`scan_guardrails`). Se
rechaza (no se cae al default silencioso) cualquier valor fuera del registro `AGENTS`.

### 2. [ALTO] Path traversal del escritor en `_prepare_ephemeral_task`
`target = tp.parent / fm["target"]` sin contención; un `target` absoluto o con `..` en el
front-matter escapaba del directorio del contrato y luego `_apply_new_code` escribía ahí el
código del modelo.

**Fix:** nuevo helper `_contained_path(base, rel)` que rechaza `rel` absoluto o no-string y
exige `cand.resolve()` dentro de `base.resolve()` vía `relative_to` (mismo patrón que
`lint_task_contract` aplica a `test_code`). Si escapa → `FAIL` con razón clara, antes de
tocar el filesystem.

### 3. [MEDIO] JSON-RPC frágil en `main`/`handle`/`handle_tools_call`
`handle(json.loads(line))` sin try/except: un request malformado (sin `name`, sin `params`,
array batch, no-dict, JSON roto) tiraba el servidor entero (KeyError/AttributeError/
JSONDecodeError, reproducido) y filtraba `str(e)` (rutas) al cliente.

**Fix:**
- `main()`: parse y dispatch por línea envueltos. JSON roto → `-32700`; no-dict → `-32600`;
  excepción en dispatch → `-32603` (detalle a stderr, no al cliente). El loop sigue vivo.
- `handle()`: usa `.get` para `params`; valida que `params` sea dict antes de
  `handle_tools_call` (`-32602` si no).
- `handle_tools_call()`: `name = params.get("name")` con validación de tipo (`-32602` si
  falta/no es string). El catch de ejecución de tool loguea el detalle a stderr y devuelve
  un mensaje genérico (no filtra rutas).

### 4. [MEDIO] SSRF/exfiltración en `judge_audit`
El schema declara solo `eval_path` pero el handler leía `provider=args.get("provider","stub")`
y `api_url=args.get("api_url","")` y los pasaba a `judge_audit.audit`: un cliente podía
redirigir las llamadas del juez Tier 2 a un endpoint arbitrario.

**Fix:** el handler deja de leer `provider`/`api_url` de `args`. Los fija el
servidor/operador por entorno (`CCDD_JUDGE_PROVIDER` default `stub`, `CCDD_JUDGE_API` default
`""`), alineado con el patrón "el MCP decide el endpoint" que ya usa `run_ephemeral_agent`.

## Tests añadidos

Nuevo archivo `tests/test_mcp_security.py` (12 tests):
- (a) `request_human_attestation` con `agent="../../x"` → error y no crea archivo fuera de
  `contracts/`; `agent` inválido rechazado; camino feliz (agent válido) sigue escribiendo.
- (b) `_prepare_ephemeral_task` rechaza `target` absoluto y con `..`; target legítimo carga.
- (c) JSON-RPC malformado: JSON roto → `-32700` y el server sigue vivo para el siguiente
  request; no-dict → `-32600`; `tools/call` sin `name` → error (no KeyError); notificación
  sin `id` sin respuesta; método no soportado → `-32601`.
- (d) `judge_audit` ignora un `api_url`/`provider` inyectado (spy sobre `judge_audit.audit`).

## Verificación

```
cd "D:\repos\Nueva carpeta (38)\ccdd-gate" && python runners/mcp_smoke.py && python -m unittest discover -s tests
```

Salida real (últimas líneas), corrida 1 y 2 idénticas:

```
OK — el servidor MCP responde el protocolo y las 4 tools del smoke funcionan.
.............................................................................................................................................................sin backend de métricas para m.cobol (lenguajes disponibles: javascript, python, tsx, typescript)
..........................................................................................................................................................................................
----------------------------------------------------------------------
Ran 343 tests in 9.109s

OK
```

Suite final: **343 tests, 0 failures, 0 errors** en ambas corridas (baseline 331 + 12 nuevos).

Complejidad de las funciones tocadas, bajo el budget del proyecto (cyclomatic ≤ 10,
nesting ≤ 3, lines ≤ 41): `request_human_attestation` cyclo=6/lines=39, `handle` cyclo=6,
`main` cyclo=6/lines=21, `_prepare_ephemeral_task` lines=31 — todas ok.

## Trade-offs

- **`request_human_attestation`:** se rechaza `agent` inválido en vez de caer al default
  silencioso (diferencia con `_agent_dir`, que sí cae). Es más seguro y más ruidoso para el
  llamador; coherente con que esta tool escribe en disco.
- **`_contained_path`:** rechaza rutas absolutas aunque apunten dentro del dir del contrato
  (más estricto que `lint_task_contract`, que cae al basename). Los contratos usan targets
  relativos por convención, así que no impacta el camino feliz.
- **`judge_audit`:** `provider`/`api_url` dejan de ser configurables por el cliente. Un
  operador que quiera un juez real (no `stub`) debe habilitarlo por entorno
  (`CCDD_JUDGE_PROVIDER`/`CCDD_JUDGE_API`), como ya pasa con el implementador.
- **`handle_tools_call`:** el mensaje de error de tool ya no incluye `str(e)` (podía tener
  rutas); el detalle va a stderr. Tests existentes no dependían de ese texto.