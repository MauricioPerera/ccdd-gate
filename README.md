# ccdd-gate

[![tests](https://github.com/MauricioPerera/ccdd-gate/actions/workflows/test.yml/badge.svg)](https://github.com/MauricioPerera/ccdd-gate/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Gates deterministas que mantienen honesto al código escrito por IA.**
Un modelo pequeño implementa; un árbitro que no se puede sobornar decide si pasó.

No es otro loop "dale al modelo grande hasta que diga que está listo". La condición de
parada no es el juicio del modelo —es un veredicto determinista: **complejidad ≤ budget
firmado + property-tests congelados que el implementador no puede ablandar**. Mismo input,
mismo veredicto, corrida a corrida.

> Construido sobre [CCDD](https://github.com/MauricioPerera/ccdd) (incluido aquí como
> `ccdd.py`, MIT). El sustrato determinista no llama a ningún LLM: el cerebro es el agente
> anfitrión (Claude Code, Cursor, etc.) que invoca estas herramientas.

---

## La idea en una frase

El **modelo grande** planifica y audita; el **modelo pequeño** (local/barato) implementa;
un **gate determinista** decide. El grande solo entra a autorar la tarea, auditar los tests
y rescatar cuando el chico se atasca. La inteligencia difusa va en el LLM; el control y el
veredicto van en código que no se puede engañar.

## Qué hay acá

| Pieza | Qué hace | LLM |
|---|---|---|
| `runners/metrics_backends.py` | Capa neutral compartida (umbrales + `severity` + `lint_results`) y registro `get_backend(language\|extension)` para backends por lenguaje | no |
| `runners/metrics.py` | Backend Python: métricas de complejidad por AST (ciclomática, anidamiento, params, longitud) | no |
| `runners/metrics_treesitter.py` | Backend universal vía tree-sitter (TS/TSX/JS) — **dep opcional**; sin ella, solo Python | no |
| `runners/pre_complexity_runner.py` | Orquestador L3 para el contrato `pre-complexity-agent` | no |
| `runners/pre_complexity_helpers.py` | Data-helpers para inyectar contexto de diseño y negocio | no |
| `runners/complexity_runner.py` | Orquestador L3 para el contrato `complexity-agent` | no |
| `runners/complexity_gate.py` | Gate determinista; CLI o hook PostToolUse de Claude Code | no |
| `runners/tc_lint.py` | Linter del **task-contract** (anti-desvarío del autor) | no |
| `runners/task_gate.py` | Veredicto unificado: tc_lint + tests congelados (Gate 1) + complejidad≤budget (Gate 2) + firma | no |
| `runners/approve_tests.py` | Firma humana de los tests (`tests_sha256`), a prueba de manipulación | no |
| `runners/orchestrator.py` | Loop **stateless**: pequeño implementa → tests fallan/complejidad falla → reintenta (sin memoria) → escala al grande | sí (worker) |
| `runners/test_audit.py` | Auditoría *advisory* de los tests contra el contrato | sí (advisory) |
| `runners/measure.py` | Harness de medición: tokens/intentos/escalados, costo vs loop grande | no |
| `runners/complexity_mcp.py` | Servidor MCP (stdio JSON-RPC) que expone el sustrato | no |
| `runners/mcp_smoke.py` | Smoke test del MCP | no |
| `runners/guardrails_lang.yaml` | Guardrails específicos por lenguaje | no |
| `contracts/` | Rubrics firmados: `pre-complexity-agent`, `complexity-agent`, `task-author-agent` | — |

## Quickstart

```bash
pip install -r requirements.txt

# 1) Gate determinista sobre un task-contract de ejemplo (PASS)
python runners/task_gate.py examples/sandbox/task.md

# 2) Tests congelados (deterministas, sin LLM): gate + gobernanza L2 (Ed25519) + reglas tc_lint
python -m unittest tests.test_gates tests.test_l2_governance tests.test_tc_lint_rules -v

# 3) Linter de un task-contract
python runners/tc_lint.py examples/sandbox/task.md
```

### Como hook de auto-validación en Claude Code

`settings.json` → `hooks.PostToolUse` con matcher `Write|Edit`:

```json
{ "command": "python runners/complexity_gate.py" }
```

Cada archivo que el agente escribe se mide con el backend de su lenguaje (por extensión, o
`--language` en CLI); si una métrica entra en CRÍTICA (umbral firmado), el hook bloquea y pide
refactor. Determinista, sin tokens. Una extensión sin backend registrado es un **no-op anunciado**
(aviso por stderr, exit 0), nunca un fallo silencioso. Hoy el único backend es Python.

### Instalación como paquete (console scripts)

Para usar ccdd-gate sin clonar ni rutas absolutas, instálalo como distribución (deja los scripts
`ccdd-mcp`, `ccdd-lint`, `ccdd-gate`, `ccdd-measure` en el PATH):

```bash
pipx install ccdd-gate        # o: uvx ccdd-gate · o: pip install ccdd-gate
```

> El **modo desde el repo** (`python runners/<x>.py`) sigue funcionando para desarrollo.
> Nota: los datos de gobernanza (rubric/attestations bajo `contracts/`, schema en la raíz) se
> resuelven en el layout del repo / instalación editable (`pip install -e .`); el núcleo
> determinista (medir/lintar/gate/MCP) funciona en cualquier modo.

### Como MCP

Con el paquete instalado, el `.mcp.json` no necesita clonar el repo ni `cwd`:

```json
{ "mcpServers": { "ccdd": { "command": "ccdd-mcp" } } }
```

Desde el repo, copiá `.mcp.json.example` a `.mcp.json`. Tools (sin LLM):

- `measure_complexity(code)` — métricas AST reales por función.
- `complexity_rubric(agent)` — el criterio gobernado (system/policies/thresholds) firmado.
- `scan_guardrails(code, agent?, language?, filename?)` — guardrails deterministas: secretos (texto-puro,
  igual en todo lenguaje), anidamiento (estructural, vía el backend del lenguaje), `dsv_check` (anti-alucinación por "drift", exige coincidencia exacta con HEAD local) y específicos por
  lenguaje opt-in (`runners/guardrails_lang.yaml`, p. ej. `no-eval`). `agent` evalúa contra ese contrato. Sin `language`, Python.
- `lint_task_contract(contract_text, test_code?)` - valida un task-contract (anti-desvarío del modelo grande).
- `run_integration_gate(task_path)` - **veredicto PASS/FAIL unificado** de un contrato YA EN DISCO (lint + aprobación de tests + tests congelados + complejidad ≤ budget), idéntico a la CLI `task_gate.py`. Para `kind:group` compone las hijas + el test de integración sobre los archivos reales (sin sandbox). El agente NO implementa: delega a `run_ephemeral_agent`.
- `request_human_attestation(code, reason)` - permite al agente pedir una excepción firmada cuando no puede reducir la complejidad por reglas de negocio.

## El loop grande/pequeño (Stateless Feedback y Evolución CEFL)

El loop es **stateless** (sin estado) pero incorpora mecánicas evolutivas inspiradas en CEFL (Candidate Expansion and Freezing):

1. **Expansión Paralela:** El orquestador no pide 1 intento; pide N candidatos paralelos (`--candidates 3`).
2. **Torneo de Complejidad (Freezing):** Cada candidato se aísla y se valida contra los tests y el budget de complejidad. Si varios pasan, el Gate elige automáticamente **el que tenga la menor puntuación matemática de complejidad**, congelándolo como la respuesta definitiva.
3. **Feedback Masivo (Partial Success):** Si todos los candidatos fallan, el sistema no reenvía código roto uno por uno. Agrupa las N soluciones fallidas junto a sus errores (stack traces) en un JSON combinado masivo. Esto permite al modelo en la siguiente iteración aprender cruzando los fracasos de todas sus rutas exploratorias, resolviendo problemas que un solo reintento jamás lograría.

```bash
# OFFLINE (sin modelo): stub que entrega 1 impl rota y 1 buena -> intento 1 FAIL, intento 2 PASS
python runners/orchestrator.py examples/sandbox/loop_demo/task.md \
  --provider stub \
  --stub examples/sandbox/loop_demo/_stub_bad.py \
  --stub examples/sandbox/loop_demo/_stub_good.py --max-attempts 3

# CON MODELOS: el pequeño genera 3 vías paralelas; si todas fallan, escala al grande
python runners/orchestrator.py examples/sandbox/loop_demo/task.md \
  --provider openai --model <modelo-chico> --candidates 3 \
  --escalate-provider ollama --escalate-model <modelo-grande> --escalate-attempts 2
```

Providers: `ollama`, `openai` (LM Studio/vLLM, urllib stdlib), `anthropic` (SDK), y `stub`
(secuencia offline para probar la mecánica sin modelo).

## task-contract (formato)

Front-matter YAML (machine-checkable) + cuerpo Markdown (prescriptivo). Ver
`examples/sandbox/task.md` y el rubric de autoría en `contracts/task-author-agent/`.
Regla central: **especifica el contrato y los property-tests con oráculo independiente,
NO el algoritmo**. Los tests se congelan y firman *antes* de que el implementador toque la tarea.

**Campo `language` (opcional, multi-lenguaje).** Por defecto `python`. Con `language: python`
la firma se valida con el AST nativo (preciso). Para otros lenguajes (`typescript`, `javascript`,
`go`, …) `tc_lint` valida la firma por **aridad genérica** (cuenta de parámetros top-level y
extracción de nombre, respetando `()[]{}<>` y comillas) y emite el warning `tc-signature-generic`
para señalar que no hay parser nativo. `params_max` y el resto de reglas se aplican igual.
Sin el campo, el comportamiento es idéntico al actual (Python).

## Conformancia multi-lenguaje

`fixtures/conformance/` define un **oráculo congelado** de las 4 métricas (fixtures equivalentes
por lenguaje + valores esperados). Todo backend debe reproducirlo: Python es el baseline y el
backend **TypeScript/JS** (tree-sitter) pasa la suite con métricas estructurales idénticas
(`cyclomatic`/`nesting_depth`/`parameter_count`); solo `function_length` diverge por formato y se
fija por-lenguaje. Un backend nuevo no se acepta hasta pasar `tests/test_conformance.py`. Ver
[`fixtures/conformance/README.md`](fixtures/conformance/README.md).

**Multi-lenguaje hoy:** Python nativo (sin deps) + TS/TSX/JS vía tree-sitter (dep opcional:
`pip install tree_sitter tree_sitter_typescript`). El gate, el hook y `measure_complexity` miden
`.ts`/`.js` igual que `.py` cuando la dep está instalada; si no, esos archivos son no-op anunciado.

## Integración GitHub (opcional, `integrations/github/`)

Capa adaptadora **opcional**: el sustrato determinista no depende de GitHub. Sin ella, todo
funciona en local. Usa `gh` CLI; tokens por entorno, nunca en el repo.

- `reporter.py` — toma el JSON de `task_gate`/`complexity_gate` y genera un comentario Markdown
  determinista (PASS/FAIL, métricas vs budget, motivo). Idempotente: actualiza un comentario
  "marcado" en vez de spamear. Offline imprime el Markdown; `--post` lo publica vía `gh`.
- `ci_gate.py` + `.github/workflows/ccdd-gate.yml` — **GitHub Action**: en cada PR descubre los
  task-contracts afectados (el `.md` o su `target`), corre `tc_lint` + `task_gate` y **bloquea el
  merge** (exit 1) si el veredicto no pasa; publica el resumen como comentario idempotente vía el
  Reporter. Sin LLM, sin secretos (usa el `GH_TOKEN` del runner). **Copiable a un repo
  consumidor**: copia `.github/workflows/ccdd-gate.yml` e `integrations/github/` (o vendoriza/instala
  ccdd-gate) y activa branch protection sobre el check `ccdd-gate`.
- `scaffold.py` — genera el esqueleto de un task-contract desde un issue (`--issue owner/repo#N`
  o `--from-json` offline). Captura la intención (título/cuerpo/labels) con placeholders `TODO`;
  el resultado es **incompleto a propósito** (`tc_lint` lo marca, no falsamente verde).
- `lifecycle.py` — conecta el **orquestador** con el ciclo de vida del issue: un issue `ccdd:ready`
  con gate verde abre un PR enlazado (`Closes #N`) y pasa a `ccdd:in-review`; si escala → `ccdd:escalated`;
  si ni el grande pasa → `ccdd:needs-split`. El loop del orquestador no sabe de GitHub (recibe un
  callback opcional `on_result`); sin él, corre igual en local. Transiciones de label deterministas y reversibles.
- `decompose.py` — materializa task-contracts atómicos como **sub-issues** de un issue padre
  (epic/feature), con vínculo bidireccional y marker idempotente (re-ejecutar no duplica). No
  decide la descomposición (la decide el autor): solo la materializa.
- `link.py` — vínculo bidireccional contrato↔issue: `status --contract` (estado + labels) o
  `status --issue owner/repo#N` (contratos que lo referencian), y `sync-labels` (refleja el estado
  como labels `ccdd:*`, idempotente, sin pisar labels ajenas). El campo `issue` del front-matter es
  opcional; `tc_lint` valida su formato (regla `tc-issue-ref`) sin romper contratos sin él.

## Benchmarks

Ver [`BENCHMARKS.md`](BENCHMARKS.md). En resumen: el gate determinista cuesta **0 tokens** y
su lógica es **sub-milisegundo** (`python benchmarks/bench_gate.py`). La economía grande/pequeño
está medida y **honestamente etiquetada como ilustrativa** — gana por reuso/volumen, no en el
one-shot trivial (ahí es más caro).

## Honestidades (léelas antes de creerle a nadie)

- **El ahorro de tokens es condicional, no universal.** En una tarea trivial de un tiro,
  este flujo puede salir *más caro* que solo llamar al modelo grande. Gana por **volumen,
  reuso y dificultad**. Medilo vos con `runners/measure.py`; no te fíes del titular.
- **El gate es tan fuerte como sus property-tests.** Tests laxos → el modelo pequeño pasa
  basura. La auditoría del modelo grande (`test_audit.py`) y el oráculo independiente son
  lo que hace que el veredicto signifique algo.
- **`task_gate` ejecuta los tests.** En local con tus modelos es seguro; para correr código
  ajeno usá un sandbox aislado (contenedor), no el host.
- **Auditar tests requiere un modelo grande.** Un modelo de ~12B como auditor tiende a
  aprobar tests rotos. Implementar lo hace bien; auditar, no.

## Licencia

MIT © 2026 Mauricio Perera. Incluye `ccdd.py` y `ccdd_context.schema.json` del proyecto
[CCDD](https://github.com/MauricioPerera/ccdd) (mismo autor, MIT), con una única adaptación
para uso standalone: `ccdd.py` resuelve su schema junto a sí mismo (upstream lo busca en el
directorio padre). Publicado *as-is*, sin garantía ni soporte.
