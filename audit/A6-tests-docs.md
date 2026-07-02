# A6 — Calidad de tests y docs-vs-realidad — Auditoría

## Resumen

Repo auditado: `ccdd-gate` @ `main` (HEAD `15488e2`). Plataforma: Windows 11, Python 3.14.6.
Modo: READ-ONLY (no se modificó fuente; no se agregaron archivos de prueba al repo).

**Suite:** `python -m unittest discover -s tests` → **331 tests, 0 fallos, 8.34 s**.
**Bench:** `python benchmarks/bench_gate.py` → metrics 0.262 ms/op, tc_lint 1.468 ms/op, task_gate 89.18 ms/op, 0 tokens.
**tree-sitter:** instalado → backend `typescript`/`tsx`/`javascript` registrado; la suite de conformance TS corre realmente (no se salta).

**Veredicto general:** la suite es **fuerte** en el núcleo determinista (gate, conformance, mutation, L2, auditores). El oráculo de conformance es **correcto** (verificado a mano). El README es **mayoritariamente veraz** — las claims estructurales (determinismo, gates opt-in/default-on, target_line→INVALID, conformance TS, CI no-opcional) están **confirmadas contra código**. Los desajustes son: (1) **gap de test real** en el orquestador CEFL — la feature más publicitada del README no tiene ningún test que la ejerza; (2) el juez Tier 2 sólo se calibra con un stub tautológico; (3) números de BENCHMARKS.md para `tc_lint` desfasados ~2× vs. medición; (4) `test_audit.py` (el auditor advisory citado en "Honestidades") sin test.

La "tabla docs-vs-realidad" (más abajo) es el entregable clave y está **mayoritariamente en verde**.

---

## Hallazgos (tests débiles / gaps)

### [SEV: ALTO] El orquestador CEFL (candidatos paralelos, torneo, feedback masivo) NO tiene tests que lo ejerciten
- **Archivo:** `runners/orchestrator.py:96-155` (implementación) vs. `tests/test_lifecycle.py:84-90` (único test que toca `orchestrator.implement`).
- **Descripción:** El README dedica una sección entera ("El loop grande/pequeño (Stateless Feedback y Evolución CEFL)") a tres mecánicas: **Expansión Paralela** (`--candidates 3`), **Torneo de Complejidad / Freezing** (elegir el candidato de menor score), y **Feedback Masivo / Partial Success** (combinar N fallos en un JSON). El código existe: `_generate_candidates` (`orchestrator.py:96`), `_evaluate_candidates` (`:115`), `_fail_feedback` (`:125`), `run_rounds` (`:134`, ordena por `get_complexity_score` y congela el ganador, `:148-155`). Pero el único test (`test_lifecycle.py:84-90`) llama a `orchestrator.implement(...)` con un contrato **ROTO** (`BROKEN` = `intent: hace y ademas otra`, `:20`) que falla `tc-intent-atomic` y devuelve `INVALID` en la etapa de lint de contrato — **nunca llega a `run_rounds`**. Solo prueba el cableado del callback `on_result`.
- **Impacto:** La feature titular del "loop grande/pequeño" (paralelismo, torneo de complejidad, agrupamiento de fallos) podría romperse sin que la suite lo detecte. Es exactamente el modo de falla que la sección "Honestidades" dice combatir ("el gate es tan fuerte como sus property-tests") — pero acá **no hay property-test**.
- **Fix sugerido:** Un test offline con `--provider stub` y `--stub` bueno/malo + `--candidates N>1` que (a) verifique que con N candidatos donde uno pasa, el resultado es PASS y se conserva el de menor score; (b) verifique que cuando todos fallan, el feedback combina los N (`cefl_candidates == N`, `candidates_evaluations` con N entradas). El propio `examples/sandbox/loop_demo/` ya provee el harness stub para esto.

### [SEV: MEDIO] El juez Tier 2 sólo se calibra con un stub tautológico — su eficacia real es no-verificable
- **Archivo:** `tests/test_eval_gate.py:120-126` (`JudgeAuditStub.test_stub_agreement_is_total`).
- **Descripción:** El README afirma que el juez LLM Tier 2 "no cuenta hasta pasar `judge_audit`" y que éste "se calibra contra un golden set … acuerdo ≥ agreement_min". El test usa `provider="stub"` y el propio comentario lo delata: *"El provider stub devuelve el golden_judgment: acuerdo 1.0 por construcción (mecánica)"*. Es decir, el test verifica el cableado (`audit` corre, devuelve `agreement`), no que `judge_audit` detecte un juez malo. Un bug en el cálculo de `agreement` que sólo se manifieste con un juez real (no-stub) pasaría invisible.
- **Impacto:** La claim "no confía en el juez, lo mide" queda **asertada pero no probada** para el caso real. El README es honesto en que Tier 2 es opt-in, pero la auditoría del juez es su razón de ser.
- **Fix sugerido:** Añadir un test con un `provider` fake que devuelva veredictos **discrepantes** del golden set (p. ej. invierte 1 de 3) y afirmar que `agreement < agreement_min` y `ok == False`. Eso prueba que `judge_audit` efectivamente *falla al juez* cuando debe — sin need de un LLM real.

### [SEV: MEDIO] `runners/test_audit.py` (auditor advisory de tests) no tiene test
- **Archivo:** sin `tests/test_test_audit.py`; `grep -rl "test_audit" tests/` no halla referencias (los hits son `audit_annotations`/`composition`/`orphan`, módulos distintos).
- **Descripción:** La sección "Honestidades" del README apoya la validez del veredicto en dos cosas: el oráculo independiente y "la auditoría del modelo grande (`test_audit.py`)". El módulo `runners/test_audit.py` existe y la tabla del README lo marca `LLM: sí (advisory)`, pero **ningún test lo cubre**. Es el único runner con LLM que carece de test (el orquestador al menos tiene el test de callback).
- **Impacto:** El Advisory que el README cita como garantía de fuerza del oráculo no está gateado ni testeado. Si se rompe, "tests laxos → modelo pequeño pasa basura" queda sin la segunda línea de defensa que el README promete.
- **Fix sugerido:** Test determinista de la **salida** de `test_audit.py` (no del LLM): feed de un test-contract con tests rotos conocidos y asertar que el reporte advisory los enumera (mock del cliente LLM, o un provider stub que devuelva un juicio prefijado).

### [SEV: BAJO] `BENCHMARKS.md`: valor de `tc_lint` desfasado ~2× y claim "sub-milisegundo" contradicha para lint
- **Archivo:** `BENCHMARKS.md:16-18` (tabla "~0.71 ms/op" para tc_lint) y `:23` ("la lógica del gate (métricas + lint) es sub-milisegundo"); `README.md:350` ("su lógica es sub-milisegundo").
- **Descripción:** Medición real en esta máquina (Windows 11, Python 3.14.6 — mismo OS/Python que declara BENCHMARKS): `metrics.functions_metrics` 0.262 ms ✓ (tabla dice ~0.28, ok), `tc_lint.lint` **1.468 ms** (tabla dice ~0.71 — **~2× por debajo**), `task_gate.gate` 89 ms (tabla ~81, ok). La claim categórica "lógica del gate (métricas + lint) sub-milisegundo" queda **rota por lint solo** (1.47 ms > 1 ms).
- **Impacto:** Bajo. BENCHMARKS avisa "los números absolutos varían por máquina". Pero el desfasaje 2× es en el mismo entorno declarado, y "sub-milisegundo" es categórico, no "del orden de". Un lector que reproduzca obtiene ~2× para lint.
- **Fix sugerido:** Actualizar la tabla a ~1.5 ms para tc_lint (o re-medir y promediar), y suavizar "sub-milisegundo" a "milisegundo" o acotarlo a "métricas" (que sí es sub-ms). "0 tokens" y "byte-idéntico" siguen siendo veraces y son lo que importa.

### [SEV: BAJO] `manifest.json`: `cross_language_divergence_allowed` es declarativa — el test la ignora (inconsistencia docs/test)
- **Archivo:** `fixtures/conformance/manifest.json:160-163` (switch_case lista `nesting_depth` como divergencia permitida) vs. `tests/test_conformance.py:25-29` (`expected_for` sólo aplica `language_overrides`, **no** lee `cross_language_divergence_allowed`).
- **Descripción:** El README/manifest dicen que para `switch_case` un backend puede contar el `switch` como nivel de anidamiento y se "fija por-lenguaje". Pero **no hay `language_overrides.typescript.nesting_depth`** para switch_case, y el test compara `nesting_depth` estrictamente contra `expected+overrides`. Un backend TS que contara el switch como nesting **fallaría** el test pese a que el manifest lo "permite".
- **Impacto:** En realidad esto hace al test **más estricto** que la promesa del manifest (más seguro, no menos). La inconsistencia es documental: el manifest sugiere una flexibilidad que el test no concede. No hay riesgo de que pase un backend divergente.
- **Fix sugerido:** O bien añadir `language_overrides.typescript.nesting_depth` para switch_case si se quiere honrar la divergencia, o bien remover `nesting_depth` de `cross_language_divergence_allowed` y documentar que las estructurales son no-divergentes siempre. Aclarar en el README que `cross_language_divergence_allowed` es **informativo** y el oráculo duro es `expected`+`language_overrides`.

---

## Tabla docs-vs-realidad (afirmación | veredicto | evidencia archivo:linea)

| # | Afirmación del README/BENCHMARKS | Veredicto | Evidencia |
|---|---|---|---|
| 1 | "100% determinista / sin LLM en el veredicto" (gate de código) | **CONFIRMADA** | `runners/task_gate.py:421-443` `gate()` sólo usa `ast`, `subprocess` (corre los *tests congelados del usuario*, no un LLM) y hashes. Sin imports de openai/anthropic/urllib. `grep` de LLM/http en `eval_gate.py` sólo matchea el docstring que lo niega (`:2`,`:11-12`). |
| 2 | "gate-signature es default-on" | **CONFIRMADA** | `runners/task_gate.py:436` — `_gate_signature` se llama **incondicionalmente** en la cadena `or` (no hay `if fm.get(...)` que la gatee); sólo cede (`:318-319`) si la fn no es resoluble. |
| 3 | Gates opt-in (pure, forbid_mutable_defaults, forbid_bare_except, forbid_assert, forbid_none_eq) existen y son default-off | **CONFIRMADA** | `task_gate.py:331,347,363,379,395` — cada uno `if not fm.get("<flag>"): return None`. Test `tests/test_purity_gate.py:90-95` verifica back-compat (impuro sin `pure` → PASS). |
| 4 | "target_line desambigua homónimos; sin él, INVALID (no mide la última en silencio)" | **CONFIRMADA** | `runners/task_gate.py:105-109` — `if len(matches) > 1: return INVALID`. `tests/test_homonymous_target.py:106-114` (sin target_line → INVALID con `candidate_lines`) y `:116-135` (con target_line mide la correcta). |
| 5 | "TS/JS pasa conformance con métricas idénticas salvo function_length" | **CONFIRMADA** | `tests/test_conformance.py:53-67` passed (TS registrado). Verificado a mano: `deep_nesting` TS cyc=5/nesting=5/params=1 (==Python), len=15 (override); `switch_case` cyc=5/nesting=0/params=1; `boolop_chain` cyc=4/nesting=0/params=4. Estructurales idénticas, `function_length` diverge y se fija por `language_overrides`. |
| 6 | "el CI corre auditorías no-opcionales (audit_composition, audit_annotations, mutation_audit)" | **CONFIRMADA** | `integrations/github/ci_gate.py:163-165` corre los tres; `:172` `ok = overall_pass(...) and audit.get("ok") and ann.get("ok") and not survivors` → exit 1 si cualquiera falla. `.github/workflows/ccdd-gate.yml` invoca `ci_gate.py --post` (no hay step separado; viven dentro del driver, por eso son no-opcionales). |
| 7 | "una extensión sin backend registrado es no-op anunciado (exit 0)" | **CONFIRMADA** | `tests/test_language_dispatch.py:65-71` — archivo `.cobol` → returncode 0 y stderr contiene "sin backend". |
| 8 | "tc_lint valida firma por aridad genérica para non-python y emite warning `tc-signature-generic`" | **CONFIRMADA** | `runners/tc_lint.py:102-128` (`_parse_sig_generic`, `parse_sig` dispatcha por `_NATIVE_SIG`); `:166-168` emite `{"rule":"tc-signature-generic","level":"warn"}`. |
| 9 | BENCHMARKS: "0 tokens" para el gate | **CONFIRMADA** | `bench_gate.py` salida: "0 tokens LLM". El gate no invoca ningún modelo. |
| 10 | BENCHMARKS: "lógica del gate (métricas + lint) sub-milisegundo" + tabla tc_lint ~0.71 ms | **PARCIAL** | Medido: metrics 0.262 ms (✓ sub-ms, tabla ~0.28 ok), **tc_lint 1.468 ms** (>1 ms, tabla ~0.71 ≈ 2× bajo). "Sub-milisegundo" cierto para métricas, **falso para lint**. Caveat "varía por máquina" aplica, pero el desfasaje es en el mismo entorno declarado (Win/Py3.14). |
| 11 | "el juez Tier 2 es opt-in y no cuenta hasta pasar judge_audit (acuerdo ≥ min)" | **PARCIAL** | El mecanismo existe (`runners/judge_audit.py`, `ci_gate` no lo invoca → efectivamente opt-in). Pero el único test (`tests/test_eval_gate.py:120-126`) usa `provider="stub"` que **devuelve el golden** → acuerdo 1.0 por construcción (tautológico). La capacidad de *rechazar* un juez malo no está probada. |
| 12 | "run_ephemeral_agent — el servidor fija modelo/endpoint; default qwen3-coder:480b-cloud vía Ollama" | **NO-VERIFICABLE** | No se ejecutó el servidor MCP ni el agente efímero en esta auditoría (fuera de alcance, requiere Ollama/models). La tool MCP está registrada y `runners/` contiene el código; no se inspeccionó el default de endpoint. |
| 13 | "Honestidades: `task_gate` ejecuta los tests; corre código ajeno en sandbox aislado" | **CONFIRMADA** | `runners/task_gate.py:77-84` `subprocess.run(cmd, ...)` ejecuta `test_command`. El aviso de sandbox es documental (correcto). |
| 14 | "Honestidades: la auditoría del modelo grande (`test_audit.py`) hace que el veredicto signifique algo" | **PARCIAL** | `runners/test_audit.py` existe (advisory, LLM), pero **no tiene test** (gap A6-MEDIO arriba). La promesa no está respaldada por la suite. |
| 15 | "el gate es tan fuerte como sus property-tests" (mutation_audit como medidor de fuerza) | **CONFIRMADA** | `runners/mutation_audit.py` + `tests/test_mutation_audit.py:34-53` distingue oráculo fuerte (mata todos, score 1.0) de débil (deja sobreviviente) — el test **realmente** cambia la prueba para mostrar ambos outcomes. |

---

## Integridad del oráculo de conformance (resultado)

**Oráculo correcto.** Recalculé a mano las 4 métricas para los 7 fixtures Python y coinciden con `manifest.json`:

| fixture | cyclomatic | nesting | params | len | chequeo manual |
|---|---|---|---|---|---|
| simple | 1 | 0 | 1 | 2 | base, sin decisiones, 2 líneas ✓ |
| deep_nesting | 5 | 5 | 1 | 8 | for+if+while+if = +4 → 5; anidamiento 5 niveles; 8 líneas ✓ |
| many_params | 1 | 0 | 6 | 2 | 6 params ✓ |
| long_function | 1 | 0 | 0 | 92 | 92 líneas (verificadas, `:1-92`) ✓ |
| boolop_chain | 4 | 0 | 4 | 2 | `a and b and c and d` → +(operandos-1)=+3 → 4 ✓ |
| comprehension | 4 | 0 | 1 | 2 | base +1(comp) +2(ifs) = 4 ✓ |
| switch_case | 5 | 0 | 1 | 10 | match +4 ramas → 5; match no suma nesting en backend Py; 10 líneas ✓ |

**El test realmente falla si un backend diverge:** `test_conformance.py:64-66` compara **los 4** métricas con `assertEqual(m[metric], exp[metric])` por `subTest(language, fixture)` — sin tolerancia. Verificado indirectamente: TS pasa (medición directa coincide). `test_python_baseline_is_complete` (`:70-76`) garantiza que Python (baseline) cubre **todos** los fixtures.

**¿"function_length se fija por-lenguaje" esconde divergencias?** No de forma peligrosa: el valor por-lenguaje es un **oráculo congelado** (el backend debe reproducirlo exacto), no una tolerancia. Sí es cierto que `function_length` no deriva de un invariante cross-lenguaje (es hand-picked por formato), pero eso es **honesto y documentado** (`fixtures/conformance/README.md:17-19`, `manifest.json:7`). La única inconsistencia es `cross_language_divergence_allowed` declarativa para `nesting_depth` en switch_case (ver hallazgo BAJO) — que hace al test *más* estricto, no más laxo.

---

## Cosas que están BIEN

- **Tests no tautológicos en el núcleo.** `test_mutation_audit.py:34-53` genuinamente construye un oráculo fuerte y uno débil sobre el *mismo* target y verifica outcomes opuestos — es el patrón oro para "¿el test prueba algo?". `test_gates.py` construye variantes rotas en tempdir (impl rota, budget apretado, approval faltante) y aserta el `stage` exacto.
- **Oráculo de conformance verificado a mano** — 7/7 fixtures correctos.
- **Conformance es estricta:** sin tolerancia, `subTest` por (lenguaje,fixture), `assertGreater(checked, 0)` para no dar falso verde si todo se salta.
- **L2 governance con Ed25519 real** (`test_l2_governance.py:107-133`): keygen → cambio crítico bloqueado → attest → pasa. No simula firmas.
- **eval Tier 1 probado con agentes rotos reales** (`test_eval_gate.py:54-81`): agente que alucina fuente → `groundedness` hard violation; agente que devuelve str → FAIL controlado (no crash). Dataset manipulado → INVALID por hash.
- **audit_composition distingue deuda de forma vs comportamiento** (`test_audit_composition.py:66-84`): test que ejercita hijos reales → ok=True; test con `unittest.mock` → ok=False. Es la distinción sutil que el README promete.
- **Docs honestas:** la sección "Honestidades" admite las limitaciones correctas (ahorro condicional, gate≤tests, sandbox para código ajeno, auditor requiere modelo grande). BENCHMARKS etiqueta la economía como "ilustrativa, no rigurosa".
- **331 tests, 0 fallos, sin flakes** en una corrida; determinismo del reporter verificado (`test_reporter.py:27-32`).
- **gate-signature, opt-in gates, target_line, dispatch por lenguaje, no-op anunciado** — todos confirmados con tests que prueban tanto el happy path como el back-compat/fallo.

---

## Limitaciones de mi auditoría

- **Muestreo, no lectura exhaustiva.** Leí a fondo ~14 de 41 archivos `test_*.py` (los foco del prompt + algunos adyacentes). Los ~27 restantes (p. ej. `test_assert_check`, `test_coverage_check`, `test_sig_check`, `test_deps_check`, `test_semantic_hash`, `test_scaffold`, `test_issue_link`, `test_ci_gate`, `test_dsv_gate`, `test_mcp_*`, `test_tc_lint_*`) los muestreé por grep/encabezado, no línea a línea. Podrían contener tests débibles puntuales que no vi.
- **No ejecuté el servidor MCP, el orquestador con modelos, ni `run_ephemeral_agent`.** La claim #12 (default qwen3/Ollama) quedó NO-VERIFICABLE. Tampoco corridí `runners/measure.py` (la economía de BENCHMARKS es por diseño ilustrativa y atada a hardware/modelos que no tengo).
- **No medí `judge_audit` con un juez real** — sólo constaté que el test existente es tautológico. No puedo afirmar que el cálculo de `agreement` esté buggeado; sólo que la suite no lo probaría si lo estuviera (con un juez no-stub).
- **Una sola corrida de suite y bench.** El bench es determinista por construcción, pero no promedié múltiples corridas; los ms varían por carga de máquina. El desfasaje tc_lint (1.47 vs 0.71) es robusto como orden de magnitud pero el número exacto depende del hardware.
- **No inspeccioné `contracts/` ni `ccdd.py`** (L1/L2 schemas y rubrics) más allá de lo que `test_l2_governance` ejercita.