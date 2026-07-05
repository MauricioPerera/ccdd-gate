# ccdd-gate

[![PyPI](https://img.shields.io/pypi/v/ccdd-gate)](https://pypi.org/project/ccdd-gate/)
[![tests](https://github.com/MauricioPerera/ccdd-gate/actions/workflows/test.yml/badge.svg)](https://github.com/MauricioPerera/ccdd-gate/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Gates deterministas que mantienen honesto al código escrito por IA.**
Un modelo pequeño implementa; un árbitro que no se puede sobornar decide si pasó.

No es otro loop "dale al modelo grande hasta que diga que está listo". La condición de
parada no es el juicio del modelo —es un veredicto determinista: **complejidad ≤ budget
firmado + property-tests congelados que el implementador no puede ablandar**. Mismo input,
mismo veredicto, corrida a corrida.

El mismo principio cubre **dos pilares**:

- **Código** (gate de complejidad/tests): verifica que la función implementada respeta el budget
  y pasa los property-tests congelados. 100% determinista.
- **Comportamiento de agentes** (pilar de evals): para la salida NO determinista de un agente
  (texto/JSON), un dataset congelado + checks deterministas (schema, contención, citas/groundedness
  anti-alucinación, PII, trayectoria) deciden PASS/FAIL sin LLM (**Tier 1**); un juez LLM acotado y
  auditado contra un golden set es **Tier 2 opt-in**. Ver [Pilar de evals](#pilar-de-evals-gatear-output-no-determinista-tier-1--tier-2-opt-in).

> Construido sobre [CCDD](https://github.com/MauricioPerera/ccdd) (incluido aquí como
> `ccdd.py`, MIT). El sustrato determinista no llama a ningún LLM: el cerebro es el agente
> anfitrión (Claude Code, Cursor, etc.) que invoca estas herramientas.

## Instalación (PyPI)

`ccdd-gate` está publicado en [PyPI](https://pypi.org/project/ccdd-gate/) — esta es la vía
recomendada para usuarios (sin clonar, sin rutas absolutas):

```bash
pip install ccdd-gate
# o: pipx install ccdd-gate · uvx ccdd-gate
```

Quedan disponibles los CLIs `ccdd-lint`, `ccdd-gate`, `ccdd-measure` y el servidor MCP
`ccdd-mcp` (todos en el PATH).

### Registrar el MCP en un cliente (Claude Code / Desktop)

```json
{ "mcpServers": { "ccdd": { "command": "ccdd-mcp" } } }
```

> El **modo desde el repo** (`python runners/<x>.py`, `pip install -e .`) sigue funcionando
> para desarrollo — ver [Quickstart](#quickstart) e
> [Instalación como paquete](#instalación-como-paquete-console-scripts).

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
| `runners/metrics_treesitter.py` | Backend universal vía tree-sitter (TS/TSX/JS/Rust/Go/Java/C#/PHP) — **dep opcional**; sin ella, solo Python | no |
| `runners/pre_complexity_runner.py` | Orquestador L3 para el contrato `pre-complexity-agent` | no |
| `runners/pre_complexity_helpers.py` | Data-helpers para inyectar contexto de diseño y negocio | no |
| `runners/complexity_runner.py` | Orquestador L3 para el contrato `complexity-agent` | no |
| `runners/complexity_gate.py` | Gate determinista; CLI o hook PostToolUse de Claude Code | no |
| `runners/tc_lint.py` | Linter del **task-contract** (anti-desvarío del autor) | no |
| `runners/task_gate.py` | Veredicto unificado: tc_lint + tests congelados + complejidad≤budget + anotaciones + firma implementada (gate-signature) + deps opt-in (gate-deps) + aprobación; `kind:group` compone hijas + test de integración | no |
| `runners/deps_check.py` | `unauthorized_imports`: imports top-level de terceros NO permitidos (núcleo del enforcement de `deps_allowed` / anti-slopsquatting). AST puro | no |
| `runners/sig_check.py` | `signature_mismatch`: la firma IMPLEMENTADA vs la del contrato (nombre + nombres de params en orden); caza el drift de firma. AST puro | no |
| `runners/purity_check.py` | `impure_operations`: operaciones impuras en el cuerpo (print/open/eval/exec/__import__/input, global/nonlocal, import interno). AST puro | no |
| `runners/mutdef_check.py` | `mutable_defaults`: params con default mutable ([]/{}/set()/list()/dict()). AST puro | no |
| `runners/bareexcept_check.py` | `bare_except_lines`: líneas de `except:` desnudo (sin tipo). AST puro | no |
| `runners/assert_check.py` | `assert_lines`: líneas de `assert` (desaparecen con `python -O`). AST puro | no |
| `runners/nonecmp_check.py` | `none_eq_lines`: comparaciones con None por ==/!= (en vez de is/is not). AST puro | no |
| `runners/coverage_check.py` | `function_lines`: líneas del cuerpo que la ejecución debería cubrir (primitivo, sin etapa). AST puro | no |
| `runners/rules_gate.py` | Aplica los checks deterministas **project-wide por glob** desde un `rules.yaml` (idea declarativa estilo autorules, árbitro AST sin LLM) | no |
| `runners/linter_gate.py` | Envuelve **linters externos deterministas** como checks opt-in desde un `linters.yaml` (hermano de `rules_gate`, pero el veredicto lo emite un lexterno pineado, no AST propio); hoy solo adaptador `ruff` (dep opcional, no del paquete) | no |
| `runners/audit_composition.py` | Auditor project-wide: composición sin gatear (función importa a otra sin `kind:group`); distingue deuda de FORMA vs de COMPORTAMIENTO | no |
| `runners/audit_orphan_targets.py` | Auditor project-wide: `.py` de implementación que no son target de ningún contrato (código fuera del flujo gate); exime datos puros | no |
| `runners/audit_annotations.py` | Auditor project-wide: nombres en anotaciones sin importar/definir; caza bugs de portabilidad que lazy annotations (PEP 649) enmascara | no |
| `runners/mutation_audit.py` | Mide la fuerza del oráculo vía mutation testing determinista (mutaciones fijas → corre los tests congelados por mutante); superviviente = test débil | no |
| `runners/approve_tests.py` | Firma humana de los tests (`tests_sha256`), a prueba de manipulación | no |
| `runners/orchestrator.py` | Loop **stateless**: pequeño implementa → tests fallan/complejidad falla → reintenta (sin memoria) → escala al grande | sí (worker) |
| `runners/test_audit.py` | Auditoría *advisory* de los tests contra el contrato | sí (advisory) |
| `runners/measure.py` | Harness de medición: tokens/intentos/escalados, costo vs loop grande | no |
| `runners/complexity_mcp.py` | Servidor MCP (stdio JSON-RPC) que expone el sustrato | no |
| `runners/mcp_smoke.py` | Smoke test del MCP | no |
| `runners/guardrails_lang.yaml` | Guardrails específicos por lenguaje | no |
| `runners/eval_gate.py` | **Pilar de evals — Tier 1**: veredicto determinista sobre output NO determinista (agentes). Dataset congelado + checks (schema, contención, citas/groundedness, PII, trayectoria) | no |
| `runners/eval_checks.py` | Checkers deterministas Tier 1 (una función por check; anti-alucinación de fuentes y evaluación de trayectoria) | no |
| `runners/approve_eval_cases.py` | Firma humana del dataset de evals (`cases_sha256`), a prueba de manipulación | no |
| `runners/eval_judge.py` | **Tier 2 (opt-in)**: juez LLM acotado (modelo pinneado, temp 0) — el único módulo del pilar que llama a un LLM | sí (opt-in) |
| `runners/judge_audit.py` | Fuerza/deriva del juez: acuerdo vs golden set humano (análogo a `mutation_audit`); si baja del umbral, falla el JUEZ | sí (opt-in) |
| `contracts/` | Rubrics firmados: `pre-complexity-agent`, `complexity-agent`, `task-author-agent`, `eval-agent` (juez Tier 2) | — |

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
(aviso por stderr, exit 0), nunca un fallo silencioso. Python siempre; el resto de lenguajes
requiere la dep opcional tree-sitter (ver «Conformancia multi-lenguaje»).

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
- `scan_dependencies(code, deps_allowed?, local_roots?)` - imports top-level de terceros NO permitidos (enforcement de `deps_allowed` / anti-slopsquatting). Determinista, sin LLM. `local_roots` (lista de dirs, opcional) exime los imports que resuelvan a un módulo/paquete local bajo alguno de esos roots (mismo mecanismo que el gate 4); sin el campo, ningún módulo local se exime.
- `check_signature(source, fn_name, expected_signature)` - "" si la firma implementada coincide con la esperada (nombre + nombres de params en orden), o el desajuste. Determinista, sin LLM.
- `check_purity(source, fn_name, target_line?)` - operaciones impuras del cuerpo (`gate-purity`). Sin LLM.
- `check_mutable_defaults(source, fn_name, target_line?)` - params con default mutable (`gate-mutdef`). Sin LLM.
- `check_bare_except(source, fn_name, target_line?)` - líneas de `except:` desnudo (`gate-bareexcept`). Sin LLM.
- `check_asserts(source, fn_name, target_line?)` - líneas de `assert` (`gate-assert`). Sin LLM.
- `check_none_cmp(source, fn_name, target_line?)` - comparaciones con None por ==/!= (`gate-nonecmp`). Sin LLM.
- `run_rules_gate(rules_path?, root?)` - aplica los checks deterministas **project-wide por glob** desde un `rules.yaml`. Sin LLM.
- `run_linter_gate(linters_path?, root?)` - envuelve **linters externos deterministas** como checks opt-in desde un `linters.yaml` (lista de `{tool, version, files?, args?, required?}`); version pineada, sin LLM. Hoy solo adaptador `ruff` (dep opcional, no del paquete).
- `run_integration_gate(task_path)` - **veredicto PASS/FAIL unificado** de un contrato YA EN DISCO (lint + aprobación de tests + tests congelados + complejidad ≤ budget), idéntico a la CLI `task_gate.py`. Para `kind:group` compone las hijas + el test de integración sobre los archivos reales (sin sandbox). El agente NO implementa: delega a `run_ephemeral_agent`.
- `run_ephemeral_agent(task_path)` - delega la **implementación** al modelo pequeño local y la valida contra el gate. El **servidor** fija modelo y endpoint; el LLM anfitrión solo pasa `task_path` (no elige el modelo). El **operador** puede elegir el modelo por entorno (`CCDD_EXECUTOR_MODEL`, `CCDD_EXECUTOR_API`) sin tocar la fuente; el LLM no. Default: `qwen3-coder:480b-cloud` vía Ollama (`http://localhost:11434/v1`).
- `audit_composition(root?)` - composición sin gatear project-wide; separa deuda de FORMA (composición ejercitada por el test del composer) de deuda de COMPORTAMIENTO (mock o test ausente). `ok` = sin deuda de comportamiento.
- `audit_orphan_targets(root?)` - `.py` de implementación que no son target de ningún contrato (exime tests/`__init__`/datos puros). Para proyectos 100% CCDD.
- `audit_annotations(root?)` - nombres usados en anotaciones sin importar/definir, sobre todos los targets; caza bugs de portabilidad que Python 3.14 (lazy annotations) enmascara en runtime.
- `mutation_audit(task_path)` - fuerza del oráculo vía mutation testing determinista; un mutante sobreviviente delata un test débil. Opt-in (corre los tests por mutante).
- `request_human_attestation(code, reason)` - permite al agente pedir una excepción firmada cuando no puede reducir la complejidad por reglas de negocio.
- `run_eval_gate(eval_path)` - **pilar de evals (Tier 1)**: veredicto determinista sobre el output NO determinista de un agente (dataset congelado + checks). Sin LLM.
- `eval_rubric()` - rúbrica firmada del juez Tier 2 (contrato `eval-agent`).
- `judge_audit(eval_path, provider?)` - acuerdo del juez Tier 2 vs golden set humano; si baja del umbral, el juez no es de fiar. Provider `stub` (determinista) por defecto.

**Checklist de cierre** (antes de dar una tarea por terminada): corré las cuatro auditorías —`audit_composition`, `audit_orphan_targets`, `audit_annotations` y `mutation_audit`— hasta `ok:true`. El gate de función no cubre composición, código huérfano, anotaciones ni la fuerza del oráculo; quedarse con la auditoría que da verde y declarar "todo en verde" es el modo de falla que la checklist existe para cerrar (y que el CI hace no-opcional).

## Pilar de evals: gatear output NO determinista (Tier 1 + Tier 2 opt-in)

El gate de complejidad/tests verifica **código** (funciones con oráculo independiente). Pero un
agente de producción (un bot de soporte, un asistente de research) produce **texto/JSON no
determinista** que ese gate no cubre. El pilar de evals lo cierra **sin renunciar al determinismo
donde se puede**, en dos niveles:

- **Tier 1 — checks deterministas, sin LLM** (`eval_gate.py` + `eval_checks.py`). Sobre cada caso
  de un dataset CONGELADO y firmado (`cases_sha256`, igual que `tests_sha256`): schema del output,
  contención/ausencia de términos, `must_cite` + **groundedness** (toda cita apunta a una fuente
  existente → anti-alucinación), PII, y **evaluación de trayectoria** (tools requeridas/prohibidas,
  `max_steps`). Veredicto = función del budget: `pass_rate ≥ pass_rate_min` y violaciones duras
  ≤ `forbidden_violations_max`. **Mismo input → mismo veredicto.** Muchos agentes (extracción,
  clasificación, routing) se gatean 100% aquí.

- **Tier 2 — juez LLM ACOTADO, opt-in** (`eval_judge.py` + `judge_audit.py`). Solo para lo
  genuinamente subjetivo (coherencia, utilidad). El modelo se pinnea (`temperature 0`) y su
  veredicto **no cuenta hasta pasar `judge_audit`**: el juez se calibra contra un golden set
  atestado por humano y debe alcanzar `agreement ≥ agreement_min`. Es a la calidad lo que
  `mutation_audit` es al oráculo: no confía en el juez, lo mide. La única relajación de
  determinismo (el score por-corrida del LLM) queda acotada y auditada; cualquier deriva del modelo
  pinneado la caza `judge_audit` en CI.

```bash
# Firmar el dataset (OK humano, congela los casos)
python runners/approve_eval_cases.py examples/eval/support-bot-refunds/eval.md

# Veredicto Tier 1 (sin LLM, reproducible)
python runners/eval_gate.py examples/eval/support-bot-refunds/eval.md

# Calibrar el juez Tier 2 contra el golden set (offline con provider stub)
python runners/judge_audit.py examples/eval/support-bot-refunds/eval.md
```

El **eval-contract** (front-matter YAML + cuerpo, espeja al task-contract) declara `target`,
`agent_entry`, `dataset`, `budget`, `deterministic_checks` y el bloque `judge` (opt-in). Ver
`examples/eval/support-bot-refunds/` para el ejemplo end-to-end (agente determinista de juguete,
dataset firmado, schema y rúbrica).

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

**Campo `target_line` (opcional, desambiguación).** El gate de complejidad resuelve la función
objetivo por nombre. Si el target tiene **varias funciones/métodos homónimos** (p. ej. `set` en
varias clases), declara `target_line: N` (la línea de la def correcta) para que mida esa y no otra.
Sin desambiguador y con >1 def del nombre, el gate devuelve **INVALID** (ambiguo) en vez de medir la
última en silencio (issue #41). Con un solo match el campo es innecesario (comportamiento idéntico).

**Campo `enforce_deps` (opcional, anti-slopsquatting).** Si `enforce_deps: true`, el gate corre la
etapa **gate-deps**: flaggea los imports top-level del target que no estén en `deps_allowed` (ni en
la stdlib) y falla con `stage: gate-deps`. **Opt-in** (default off): los contratos que no lo declaran
no cambian. Los módulos **locales del propio proyecto** se eximen automáticamente: el gate pasa como
raíces de búsqueda locales el directorio del contrato y el del target, así que un import top-level que
resuelva a `<dir>/m.py` o `<dir>/m/__init__.py` bajo alguno de esos dirs no se flaggea (no hace falta
listarlo en `deps_allowed`). Los imports de tercero no listados siguen flaggeándose normalmente.
Limitación actual: la exención solo mira el top-level de esos dos dirs (no recursiva ni configurable a
otros dirs del repo); y sigue siendo solo Python.

**Conformidad de firma (etapa gate-signature, default-on).** El gate compara la firma IMPLEMENTADA
con la `signature` del contrato (nombre + nombres de parámetros en orden; ignora anotaciones,
defaults y retorno) y falla con `stage: gate-signature` si difieren — caza el drift de firma que
rompe a los callers. Es **default-on**: no requiere campo. Solo Python (compara vía AST).

**Gates de antipatrones opt-in (default-off, Python, vía AST).** Cada uno corre solo si el contrato
declara su campo; sin él, el contrato no cambia. Todos fallan con su propio `stage`:

| Campo | Etapa | Falla si la función… |
|---|---|---|
| `pure: true` | `gate-purity` | tiene operaciones impuras (print/open/eval/exec/`__import__`/input, global/nonlocal, import interno) |
| `forbid_mutable_defaults: true` | `gate-mutdef` | tiene params con default mutable (`[]`/`{}`/`set()`/`list()`/`dict()`) |
| `forbid_bare_except: true` | `gate-bareexcept` | tiene un `except:` desnudo (sin tipo) |
| `forbid_assert: true` | `gate-assert` | usa `assert` (desaparece con `python -O`) |
| `forbid_none_eq: true` | `gate-nonecmp` | compara con None usando `==`/`!=` en vez de `is`/`is not` |

Cada uno honra `target_line` para funciones homónimas y tiene su tool MCP (`check_purity`,
`check_mutable_defaults`, `check_bare_except`, `check_asserts`, `check_none_cmp`).

**Reglas project-wide por glob (`rules_gate`).** Los gates de antipatrón de arriba se disparan
**por contrato**. Para aplicarlos a TODO el repo sin contratos, `runners/rules_gate.py` lee un
`rules.yaml` declarativo (lista de `{check, files}`) y corre el check determinista sobre cada función
de los archivos que matchean el glob — política de repo, no solo por función gateada. La idea del
formato declarativo + glob está tomada de [autorules](https://github.com/markwylde/autorules), pero
el **árbitro es AST determinista, no un LLM** (autorules usa un juez LLM; ccdd-gate no). Ver
`examples/rules.yaml.example` y la evaluación completa en
[`docs/evaluations/autorules.md`](docs/evaluations/autorules.md).

```bash
python runners/rules_gate.py rules.yaml [root]   # exit 0 ok · 1 violaciones · 2 config inválida
```

**Linters externos deterministas (`linter_gate`).** Hermano de `rules_gate` pero el veredicto lo emite un
**linter externo** invocado como subproceso con salida machine-readable, no un AST propio: el gate no
reimplementa reglas, delega en la herramienta y solo normaliza su salida a `findings`. **Opt-in** desde un
`linters.yaml` declarativo (lista de `{tool, version, files?, args?, required?}`). La salida de un linter
depende de su versión, por eso `version` es **pin exacto obligatorio**: versión instalada != pin → entorno
inválido (exit 2, **no es PASS**). Tool ausente + `required:false` → skip anunciado + exit 0 (precedente
tree-sitter del repo); `required:true` → exit 2. Findings → exit 1; limpio → exit 0. **HOY solo hay
adaptador `ruff`** (el registro queda listo para clippy/eslint/golangci-lint sin implementarlos); **`ruff`
NO es dependencia del paquete** — es una dep opcional que el operador instala y pinea. Ver
`examples/linters.yaml.example`.

```bash
python runners/linter_gate.py linters.yaml [root]   # exit 0 limpio · 1 findings · 2 config/entorno inválido
```

**Dogfooding:** el propio repo se gatea con su `linters.yaml` de raíz (`ruff==0.15.20`, `required: true`,
excluye `fixtures/`+`examples/`+`ccdd.py`, ignora `E731`/`E402`) — paso bloqueante del CI (`.github/workflows/test.yml`).

**Campo `language` (opcional, multi-lenguaje).** Por defecto `python`. Con `language: python`
la firma se valida con el AST nativo (preciso). Para otros lenguajes (`typescript`, `javascript`,
`go`, …) `tc_lint` valida la firma por **aridad genérica** (cuenta de parámetros top-level y
extracción de nombre, respetando `()[]{}<>` y comillas) y emite el warning `tc-signature-generic`
para señalar que no hay parser nativo. `params_max` y el resto de reglas se aplican igual.
Sin el campo, el comportamiento es idéntico al actual (Python).

## Conformancia multi-lenguaje

`fixtures/conformance/` define un **oráculo congelado** de las 4 métricas (fixtures equivalentes
por lenguaje + valores esperados). Todo backend debe reproducirlo: Python es el baseline y los
backends **tree-sitter** (TS/TSX/JS/Rust/Go/Java/C#/PHP) pasan la suite con métricas estructurales
idénticas (`cyclomatic`/`nesting_depth`/`parameter_count`); solo `function_length` diverge por
formato y se fija por-lenguaje. Un backend nuevo no se acepta hasta pasar
`tests/test_conformance.py`. Ver
[`fixtures/conformance/README.md`](fixtures/conformance/README.md).

**Multi-lenguaje hoy (métricas de complejidad):** Python nativo (sin deps) + TS/TSX/JS/Rust/Go/Java/C#/PHP
vía tree-sitter (dep opcional: `pip install tree_sitter tree_sitter_typescript tree_sitter_rust
tree_sitter_go tree_sitter_java tree_sitter_c_sharp tree_sitter_php`). El gate, el hook y
`measure_complexity` miden esas extensiones igual que `.py` cuando las gramáticas están instaladas;
si no, esos archivos son no-op anunciado. Los checks de antipatrones (`gate-mutdef`, `gate-assert`,
`gate-signature`, `gate-deps`, etc.) siguen siendo **Python-only** (AST nativo).

## Integración GitHub (opcional, `integrations/github/`)

Capa adaptadora **opcional**: el sustrato determinista no depende de GitHub. Sin ella, todo
funciona en local. Usa `gh` CLI; tokens por entorno, nunca en el repo.

- `reporter.py` — toma el JSON de `task_gate`/`complexity_gate` y genera un comentario Markdown
  determinista (PASS/FAIL, métricas vs budget, motivo). Idempotente: actualiza un comentario
  "marcado" en vez de spamear. Offline imprime el Markdown; `--post` lo publica vía `gh`.
- `ci_gate.py` + `.github/workflows/ccdd-gate.yml` — **GitHub Action**: en cada PR descubre los
  task-contracts afectados (el `.md` o su `target`), corre `tc_lint` + `task_gate` y **bloquea el
  merge** (exit 1) si el veredicto no pasa; publica el resumen como comentario idempotente vía el
  Reporter. Además corre **no-opcionalmente** `audit_composition` y `audit_annotations`
  project-wide y `mutation_audit` sobre los contratos afectados: composición sin gatear, anotaciones
  sin importar o mutantes sobrevivientes también ponen el check en rojo (lo que el autor tiende a
  saltar cuando es opt-in, acá no se puede saltar). Sin LLM, sin secretos (usa el `GH_TOKEN` del
  runner). **Copiable a un repo consumidor**: copia `.github/workflows/ccdd-gate.yml` e
  `integrations/github/` (o vendoriza/instala ccdd-gate) y activa branch protection sobre el check
  `ccdd-gate`.
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
