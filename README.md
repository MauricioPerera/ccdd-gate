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
| `runners/metrics.py` | Métricas de complejidad por AST (ciclomática, anidamiento, params, longitud) | no |
| `runners/complexity_gate.py` | Gate determinista; CLI o hook PostToolUse de Claude Code | no |
| `runners/tc_lint.py` | Linter del **task-contract** (anti-desvarío del autor) | no |
| `runners/task_gate.py` | Veredicto unificado: tc_lint + complejidad≤budget + tests congelados + firma | no |
| `runners/approve_tests.py` | Firma humana de los tests (`tests_sha256`), a prueba de manipulación | no |
| `runners/orchestrator.py` | Loop: pequeño implementa → gate → reintenta → escala al grande | sí (worker) |
| `runners/test_audit.py` | Auditoría *advisory* de los tests contra el contrato | sí (advisory) |
| `runners/measure.py` | Harness de medición: tokens/intentos/escalados, costo vs loop grande | no |
| `runners/complexity_mcp.py` | Servidor MCP (stdio JSON-RPC) que expone el sustrato | no |
| `contracts/` | Rubrics firmados: `pre-complexity-agent`, `complexity-agent`, `task-author-agent` | — |

## Quickstart

```bash
pip install -r requirements.txt

# 1) Gate determinista sobre un task-contract de ejemplo (PASS)
python runners/task_gate.py examples/sandbox/task.md

# 2) Tests congelados (deterministas, sin LLM): gate + gobernanza L2 (firmas Ed25519 reales)
python -m unittest tests.test_gates tests.test_l2_governance -v

# 3) Linter de un task-contract
python runners/tc_lint.py examples/sandbox/task.md
```

### Como hook de auto-validación en Claude Code

`settings.json` → `hooks.PostToolUse` con matcher `Write|Edit`:

```json
{ "command": "python runners/complexity_gate.py" }
```

Cada `.py` que el agente escribe se mide; si una métrica entra en CRÍTICA (umbral firmado),
el hook bloquea y pide refactor. Determinista, sin tokens.

### Como MCP

Copiá `.mcp.json.example` a `.mcp.json`. Expone 4 tools (sin LLM):

- `measure_complexity(code)` — métricas AST reales por función.
- `complexity_rubric(agent)` — el criterio gobernado (system/policies/thresholds) firmado.
- `scan_guardrails(code)` — guardrails deterministas (secretos, anidamiento).
- `lint_task_contract(contract_text, test_code?)` — valida un task-contract antes de emitirlo.

## El loop grande/pequeño

```bash
# OFFLINE (sin modelo): stub que entrega 1 impl rota y 1 buena -> intento 1 FAIL, intento 2 PASS
python runners/orchestrator.py examples/sandbox/loop_demo/task.md \
  --provider stub \
  --stub examples/sandbox/loop_demo/_stub_bad.py \
  --stub examples/sandbox/loop_demo/_stub_good.py --max-attempts 3

# CON MODELOS: el pequeño (LM Studio/Ollama) implementa contra el gate; escala al grande si se atasca
python runners/orchestrator.py examples/sandbox/loop_demo/task.md \
  --provider openai --model <modelo-chico> \
  --escalate-provider ollama --escalate-model <modelo-grande> --escalate-attempts 2
```

Providers: `ollama`, `openai` (LM Studio/vLLM, urllib stdlib), `anthropic` (SDK), y `stub`
(secuencia offline para probar la mecánica sin modelo).

## task-contract (formato)

Front-matter YAML (machine-checkable) + cuerpo Markdown (prescriptivo). Ver
`examples/sandbox/task.md` y el rubric de autoría en `contracts/task-author-agent/`.
Regla central: **especifica el contrato y los property-tests con oráculo independiente,
NO el algoritmo**. Los tests se congelan y firman *antes* de que el implementador toque la tarea.

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
