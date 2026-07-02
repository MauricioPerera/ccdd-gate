# A4 — Evals y gobernanza/firmas — Auditoría

Alcance: `runners/eval_gate.py`, `eval_checks.py`, `eval_judge.py`, `judge_audit.py`,
`approve_tests.py`, `approve_eval_cases.py`, `mutation_audit.py`, `review_attestations.py`,
`semantic_hash.py`, `task_gate.py` (gate de aprobación de tests), `ccdd.py` (Ed25519 + R4–R9),
`tests/test_l2_governance.py`, `contracts/*/expected-hashes.json`. READ-ONLY: no se modificó fuente.
Todo el tamper se hizo en copias en `tempfile.mkdtemp()` del sistema, fuera del repo.

---

## Resumen

Dos mecanismos de integridad conviven y **no son igual de sólidos**:

- **`cases_sha256` (datasets de evals): SÓLIDO.** `approve_eval_cases.py` y `eval_gate.py`
  usan **el mismo** `dataset_digest` (sha256 sobre bytes LF-normalizados). El gate re-verifica
  el hash antes de correr; un dataset manipulado se detecta (lo demostré, §"Prueba de tamper").
- **`tests_sha256` (property-tests): ROTO.** `approve_tests.py` firma con **hash semántico**
  (AST, `semantic_hash.get_semantic_hash`) pero `task_gate._gate_test_approval` verifica con
  **sha256 crudo de bytes**. Son algoritmos distintos: el verificador **nunca** acepta lo que
  firma el firmador, ni siquiera re-firmando. Los ejemplos que funcionan (`examples/batch/*`)
  fueron firmados por **otra vía** (hash crudo, consistente con `integrations/github/link.py`),
  no por `approve_tests.py`. Usar `approve_tests.py` sobre ellos los rompería.
- **Gobernanza L2 (Ed25519, `ccdd.py`): correcta** para los slots `.txt` actuales. Verificación
  fail-closed, sin firma → sin plaza, quórum respetado, R8/R9 bloquean debilitamiento.
- **Pero la atestación de EXCEPCIÓN de complejidad (`review_attestations.py` + `complexity_gate.py`)
  NO verifica firma Ed25519**: acepta la excepción por coincidencia de hash únicamente, con una
  firma simulada literal. El escape hatch del Complexity Gate no está criptográficamente gobernado.

Seis hallazgos (2 CRÍTICOS, 2 ALTOS, varios MEDIO/BAJO). El más grave: la herramienta que
documenta el README como "Firma humana de los tests, a prueba de manipulación" produce hashes
que su propio gate rechaza.

---

## Hallazgos

### [SEV: CRÍTICO] `approve_tests.py` y `task_gate.py` usan algoritmos de hash distintos — el firmador produce lo que el verificador rechaza

- Archivo: `runners/approve_tests.py:55` (firma con `semantic_hash.get_semantic_hash`) vs
  `runners/task_gate.py:42` (verifica con `hashlib.sha256(tests.read_bytes())`).
- Descripción: `approve_tests.py` escribe en `tests_sha256` el **hash semántico** del test
  (para `.py`: `sha256(ast.dump(tree))`, que ignora comentarios/espacios; ver
  `runners/semantic_hash.py:10-16`). `task_gate._gate_test_approval` compara ese campo contra
  el **sha256 crudo de los bytes** del archivo. Para un test `.py` estos dos valores **nunca
  coinciden**. El `README.md:86` y `task_contract.schema.json:44` dicen "sha256 byte-exacto";
  el firmador no cumple eso.
- Impacto: cuando un contrato pone `require_test_approval: true` y los tests se firman con
  `approve_tests.py`, el gate **siempre** sale `INVALID/test-approval` ("los tests cambiaron
  desde la aprobación"), incluso con tests intactos y **aunque se re-firme**. El mecanismo de
  congelamiento de tests —pieza central de la promesa "el implementador no puede ablandar el
  oráculo"— es inutilizable tal como se entrega. Los ejemplos `examples/batch/{popcount,clamp,
  chunk,hamming}/task.md` (que sí prenden `require_test_approval: true`) guardan hash **crudo**
  (`raw==stored` cierto, `sem==stored` falso en los cuatro), o sea **no fueron firmados con
  `approve_tests.py`**. `approve_tests --check` los reporta `DESINCRONIZADO`; ejecutar
  `approve_tests` en modo escritura los **rompería**.
- Repro (salida real, sobre el ejemplo del repo, tests intactos, sólo se añadió
  `require_test_approval: true` y luego se re-firmó con la tool oficial):

  ```
  === gate con require_test_approval=true, tests intactos ===
  rc 2
  { "verdict": "INVALID", "stage": "test-approval",
    "detail": "los tests cambiaron desde la aprobación (hash no coincide)...",
    "approved": "c339d9cff0ae59b4fdf37c6f36a538e1942e573b9c4040e3ac9fbfd4b855d9ce",  ← semántico (lo escribe approve_tests)
    "actual":   "cdf60f86f46822a9cd1201b7719e1e524846a18f70ad3caee8c9a4da3914f8ad" }  ← crudo (lo que calcula el gate)

  === re-firmar con approve_tests.py y volver a correr el gate ===
  approve: FIRMADO  test_decode_instruction.py  tests_sha256=c339d9cff0ae59b4...   ← re-escribe el mismo semántico
  rc 2  →  INVALID/test-approval, mismo desacuerdo. Re-firmar NO lo resuelve.
  ```
  Y sobre un ejemplo batch realmente firmado (con hash crudo):
  ```
  $ python runners/approve_tests.py examples/batch/popcount/task.md --check
  DESINCRONIZADO  tests=test_popcount.py  actual=663ed01cf969...  aprobado=697191cd53a2...
  $ python runners/task_gate.py examples/batch/popcount/task.md   → PASS  (el gate sí acepta el hash crudo)
  ```
- Fix sugerido: unificar el algoritmo. Lo más seguro y coherente con `cases_sha256` y con
  `integrations/github/link.py:82` (que ya usa `sha256(read_bytes())`) es que `approve_tests.py`
  firme **sha256 crudo de bytes** (idealmente LF-normalizado como `dataset_digest`, para
  portabilidad CRLF). Eliminar el uso de `semantic_hash` en `approve_tests.py:55`. Alternativa:
  que el gate use `semantic_hash` —pero entonces el congelamiento deja de ser byte-exacto (un
  implementador podría reordenar/comentar el test sin invalidar la firma), lo cual debilita la
  promesa. Recomendar lo primero. Añadir un test de integración `approve_tests → task_gate` que
  hoy **no existe** (ver hallazgo BAJO: el test que hay enshrina el bug).

---

### [SEV: CRÍTICO] La atestación de EXCEPCIÓN de complejidad no verifica firma Ed25519 — el escape hatch del Complexity Gate no está gobernado

- Archivo: `runners/review_attestations.py:55-59` (escribe `"signature":
  "simulated-signature-for-complexity"`, constante literal) y `runners/complexity_gate.py:73`
  (`exempt = any(exc.get("content_sha256") == h for exc in exceptions)` — **sólo compara hash,
  nunca llama a `verify_attestation` ni lee la firma**).
- Descripción: el flujo `request_human_attestation` (MCP) → `pending_attestations/*.json` →
  `review_attestations.py` → `contracts/<agent>/attestations.json` → `complexity_gate._is_exempt`
  es el **escape hatch** humano para un umbral estructural insalvable. El comentario en
  `review_attestations.py:53` dice "En un entorno real se pediría la clave privada Ed25519 y se
  usaría `ccdd.sign_attestation`". Es decir: hoy **no se firma**. Y `complexity_gate.py` ni
  siquiera verificaría la firma si existiera: concede la exención por **coincidencia de
  `content_sha256`** únicamente.
- Impacto: cualquiera con acceso de escritura a `contracts/complexity-agent/attestations.json`
  puede eximir **cualquier** función del Complexity Gate añadiendo
  `{"content_sha256": "<hash semántico>", "signature": "x"}`. No hay revisor, no hay clave
  pública, no hay quórum, no hay registro de confianza. La promesa de gobernanza L2 (Ed25519,
  `reviewers.json`, R7) **no se aplica** a la excepción de complejidad, que es justo el caso en
  el que un agente podría querer saltarse el gate. Comparar con `ccdd.py:84-96` `valid_signers`,
  que sí exige clave en el registro + `verify_attestation` + coincidencia de hash: la excepción
  de complejidad no usa nada de eso.
- Repro (salida real): crear una entrada falsa en `contracts/complexity-agent/attestations.json`
  con el hash semántico de una función sobre-presupuestada y `signature: ""` →
  `complexity_gate` responde `PASS (EXCEPCIÓN FIRMADA para hash …)` y retorna 0. No hay
  verificación criptográfica ninguna. (No lo ejecuté contra el repo para no tocar fuente; la
  lógica es legible en `complexity_gate.py:73`.)
- Fix sugerido: reutilizar el esquema de `ccdd.py` (`sign_attestation`/`verify_attestation` +
  `reviewers.json` + quórum). `review_attestations.py` debe exigir la clave privada Ed25519 del
  revisor y firmar `slot:hash`; `complexity_gate._is_exempt` debe llamar a `valid_signers` (o
  equivalente) y exigir firma válida de un revisor registrado, no sólo match de hash.

---

### [SEV: ALTO] `tests_sha256` es OPT-IN (`require_test_approval` default false) — el sandbox firma tests pero no los congela; el tamper no se detecta

- Archivo: `runners/task_gate.py:37-39` (retorna `None` si `require_test_approval` no está);
  `examples/sandbox/task.md:14` (declara `tests_sha256` pero **sin** `require_test_approval`).
- Descripción: el gate de aprobación de tests sólo corre si el contrato lo prende explícitamente.
  El sandbox —ejemplo canónico del README— guarda `tests_sha256` pero no activa la verificación,
  así que el hash es **decorativo**: el gate nunca lo consulta.
- Impacto: un implementador puede editar el test (ablandar el oráculo) y obtener `PASS` sin que
  el gate lo cace. Lo demostré en §"Prueba de tamper": ablandar `self.assertEqual(size,
  OPCODES_ORACLE[op])` → `pass` y el gate pasó (`rc 0, verdict PASS`). El congelamiento sólo
  protege cuando el autor se acuerda de prenderlo; el default es no protección.
- Fix sugerido: default-on para `require_test_approval` (o hashear y reportar drift siempre),
  alineado con el hallazgo homónimo de `audit/A1-core.md`. (A1 ya lo señaló; lo reconfirmo y, además,
  el fix de A1 "tests_sha256 es raw-bytes, integridad fuerte" **depende** de que se arregle el
  hallazgo CRÍTICO #1: hoy el firmador no escribe raw-bytes.)

---

### [SEV: ALTO] `judge_audit` con provider `stub` (el default) es tautológico: acuerdo 1.0 por construcción → siempre `ok`

- Archivo: `runners/eval_judge.py:14-17` (`judge_stub` devuelve el `golden_judgment` del caso);
  `runners/judge_audit.py:75` (`--provider` default `"stub"`); `runners/judge_audit.py:62-64`
  (`ok = n>0 and agreement >= minimum`).
- Descripción: el provider `stub` retorna literalmente el `golden_judgment` guardado en el caso,
  así que el veredicto del juez **es** el golden por definición → `agreement = 1.0` siempre →
  `ok = true` siempre (si hay ≥1 golden). El default de la CLI es `stub`: `python judge_audit.py
  eval.md` es un rubber-stamp. El comentario de `eval_judge.py:8-9` lo admite ("sirve para
  ejercitar la mecánica sin modelo"), pero la CLI no forza `--provider openai` para calibración
  real, y **no hay nada que exija haber corrido `judge_audit` con provider real** antes de
  "contar" Tier 2.
- Impacto: la promesa "el juez Tier 2 sólo cuenta si pasa `judge_audit` contra el golden set"
  se cumple trivialmente con el default: cualquier agente/CI que corra `judge_audit.py` sin
  `--provider openai` obtiene `ok=true` y habilita Tier 2 sin haber medido nada. Enmascara
  deriva real del modelo pinneado.
- Repro (salida real):
  ```
  $ python runners/judge_audit.py examples/eval/support-bot-refunds/eval.md
  { "golden_cases": 3, "agreement": 1.0, "agreement_min": 0.85, "provider": "stub", "ok": true, ... }
  ```
- Fix sugerido: (a) hacer `--provider` required o default `openai` (stub sólo como modo
  `--offline` explícito para CI de mecánica); (b) registrar el provider usado en el veredicto
  y que el consumidor de Tier 2 rechace `provider=stub` como "auditoría válida"; (c) que el
  eval-contract declare el provider esperado y el gate lo compruebe.

---

### [SEV: MEDIO] Tier 2 (juez LLM) nunca se integra en `eval_gate`; `judge.required` no lo enforce nadie

- Archivo: `runners/eval_gate.py` (no lee `fm["judge"]` en ningún sitio); `examples/eval/
  support-bot-refunds/eval.md:14-17` declara `judge.required: false`.
- Descripción: `eval_gate.gate` sólo corre Tier 1. El campo `judge` del contrato se ignora por
  completo. No hay código que bloquee `judge.required: true` si `judge_audit` no pasó, ni que
  combine el veredicto Tier 2 con el Tier 1. La separación está documentada como "Tier 2 opt-in",
  pero "opt-in" se traduce en "no existe automatización que lo haga contar o dejar de contar".
- Impacto: la frontera Tier 1/Tier 2 es convención manual/CI, no garantía del gate. Un
  contrato que declare `judge.required: true` sigue pasando/fallando sólo por Tier 1.
- Fix sugerido: si `judge.required: true`, `eval_gate` debería invocar `judge_audit` (con el
  provider declarado) y exigir `ok` para PASS, o al menos negarse a emitir PASS si no se aporta
  evidencia de auditoría del juez.

---

### [SEV: MEDIO] Divergencia latente de hash para slots estáticos `.py` (attest vs R6)

- Archivo: `ccdd.py:876` (`_attest_target_hash` usa `sha256(read_text(...))` = crudo) vs
  `ccdd.py:723,730` (`_check_r6_policy_attestation` usa `semantic_hash.get_semantic_hash` y
  pasa ese hash a `valid_signers`).
- Descripción: `cmd_attest` firma `slot:sha256_crudo(texto)` y guarda `content_sha256 = crudo`.
  `valid_signers` (R6) compara `e.content_sha256 == hhash` donde `hhash` es **semántico**. Para
  `.txt` coincide porque `semantic_hash` cae al fallback `sha256(content.encode)` (== crudo),
  ver `runners/semantic_hash.py:21-22`. Para `.py` **no** coinciden (semántico = `ast.dump`).
- Impacto: hoy enmascarado porque todos los slots estáticos de los contratos son `.txt`
  (`system.txt`, `policies.txt`, `thresholds.txt`, `env.txt`). Si se añade un slot estático
  `.py` (perfectamente válido por el schema), **toda** atestación legítima sería rechazada por
  R6 ("sin atestación") sin que el revisor pueda hacer nada — el bug del hallazgo CRÍTICO #1,
  pero en L2. `expected-hashes.json` sí es consistente (semántico ambos lados,
  `ccdd.py:129` vs `:136-139`), así que R4 no se ve afectado.
- Fix sugerido: que `_attest_target_hash` use `semantic_hash.get_semantic_hash` (mismo que R6),
  o que R6 use `sha256` crudo. Unificar criterio antes de que existan slots `.py`.

---

### [SEV: MEDIO] `groundedness` sólo valida existencia del índice, no sostenimiento; `no_pii` y `trajectory` son evadibles / parciales

- Archivo: `runners/eval_checks.py:68-74` (groundedness), `:13,77-81` (PII), `:84-96`
  (trajectory), `:55-59` (forbid_contains).
- Descripción / evadibilidad:
  - **Groundedness**: `bad = [c for c in cites if not (isinstance(c,int) and 0<=c<len(context))]`.
    Valida que la cita apunte a una fuente **existente**, no que la source **sostenga** el texto.
    Un agente puede citar el doc 0 (que existe) mientras afirma algo que el doc no dice → no es
    alucinación de *fuente* pero sí de *contenido*. Falso negativo inherente (Tier 2 debería
    cubrirlo). Aceptable como Tier 1, pero la docstring "Anti-alucinación de fuentes" es
    más estrecha de lo que el nombre sugiere.
  - **no_pii**: patrones sólo email y SSN-US (`\b\d{3}-\d{2}-\d{4}\b`). No cubre teléfonos,
    tarjetas, pasaportes, IDs nacionales no-US, direcciones. Además sólo escanea
    `output["text"]` — **no** `citations` ni `trajectory` (PII en esos campos no se caza).
  - **trajectory**: la trayectoria la **reporta el agente**; no hay verificación independiente
    de que refleje las tools realmente invocadas. Un agente que use `send_email` (prohibida)
    pero reporte `["search_docs","compose"]` pasa. El check valida el *reporte*, no la *realidad*.
    Además la comparación es `t in traj` exacta y sensible a mayúsculas/espacios: `"Send_Email"`
    o `" send_email"` evaden `forbidden_tools: ["send_email"]`.
  - **forbid_contains/must_contain**: substring case-insensitive sobre `text.lower()`. Frágil a
    acentos/puntuación: prohibido `"sí, puedes"` no casa con `"si, puedes"` (sin acento).
- Fix sugerido: (groundedness) documentar el límite explícitamente; (PII) ampliar patrones y
  escanear citations/trajectory; (trajectory) normalizar nombres de tools (lower/strip) y, si
  es posible, contrastar con un log de tools real; (forbid_contains) normalizar (quitar
  acentos/punct) antes de comparar.

---

### [SEV: MEDIO] `mutation_audit` es OPT-IN; el gate por defecto no mide fuerza del oráculo — un test débil congelado pasa silenciosamente

- Archivo: `runners/mutation_audit.py` (tool opt-in, no es stage del gate); `runners/task_gate.py:421-443`
  (el gate sólo corre lint + tests + complejidad, sin mutation).
- Descripción: el congelamiento (`tests_sha256`) garantiza que el test **no cambie**, no que
  sea **fuerte**. Un test vacuo firmado sigue siendo vacuo. `mutation_audit` sí mide fuerza
  (mutantes supervivientes → exit 1), pero **nadie lo invoca por defecto**.
- Solidez de `mutation_audit` cuando se corre: está bien hecho — los mutantes supervivientes
  **se reportan** (`survived`, `ok = not survived`, exit 1); timeout/crash no cuentan como
  supervivientes (`mutation_audit.py:80-81`); el target se restaura byte-exacto (`:109`); los
  `return None` literales se excluyen para no generar no-ops espurios (`:38-40`). Así que "un
  test débil sobrevive silenciosamente" → **dentro de mutation_audit, no** (se reporta); **en
  el flujo por defecto, sí** (nunca se mide).
- Operadores de mutación limitados (`_SWAP`, `:23-25`): cubre `Lt/LtE/Gt/GtE/Eq/NotEq/Add/Sub/
  Mult/Div/And/Or`, bool flip y `return None`. **No** cubre: mutación de literales constantes
  (`0`→`1`, `""`→"x"), `in`/`not in`, inserción/eliminación de `not`, eliminación de sentencias,
  `is`/`is not`. El `mutation_score` es una cota, no exhaustivo. Un test fuerte contra estos
  flips puede ser débil contra constantes.
- Fix sugerido: ofrecer `mutation_audit` como stage opt-in del gate (o en CI sobre los
  contratos críticos) y ampliar el set de operadores (constantes, `not`, `in`).

---

### [SEV: BAJO] Varios detalles que no rompen pero conviene corregir

- `tests/test_gates.py:102-109` `test_invalid_unapproved_tests` **enshrina el bug CRÍTICO #1**
  como esperado: prende `require_test_approval` sobre el sandbox (cuyo `tests_sha256` es
  semántico) y asserts `INVALID/test-approval`. Pasa, pero por la razón equivocada (mismatch
  semántico/crudo, no por tamper). Sin un test `approve_tests → task_gate PASS`, el bug queda
  protegido por la suite. Archivo: `tests/test_gates.py:102-109`.
- `runners/eval_judge.py:60` `PROVIDERS.get(provider, judge_stub)`: provider desconocido cae a
  `stub` **en silencio** → auditoría vacua sin aviso. Archivo: `runners/eval_judge.py:59-60`.
- `runners/eval_judge.py:28,33` `_parse_verdict`: regex `\{.*\}` greedy con `re.DOTALL` desde el
  primer `{` al último `}`; `int(d.get("score",0))` trunca floats (`4.5`→`4`) sin error. Modelos
  que envuelvan JSON en prosa con llaves pueden desparsear. Bajo riesgo (Tier 2 opt-in).
- `runners/task_gate.py:42` usa `read_bytes()` **sin normalizar LF**, a diferencia de
  `eval_gate.dataset_digest` (`:37-39`). `.gitattributes` fuerza LF, pero un checkout Windows
  con `autocrlf` o un edit manual CRLF rompería la firma de tests. Inconsistencia de criterio
  entre tests (crudo) y cases (LF-normalizado).

---

## Prueba de tamper de tests congelados (resultado real)

Caso A — **dataset de evals (`cases_sha256`), con `require_cases_approval: true`**: copia en
temp, ablando un caso (`forbid_contains: [...]` → `[]`) sin re-firmar → **detectado**:

```
rc 2
{ "verdict": "INVALID", "stage": "cases-approval",
  "detail": "los casos cambiaron desde la aprobación (hash no coincide). Re-aprueba.",
  "approved": "11b0bdd0a729f57a421d69225cca2352a3e0a3b76fede48fb527d46a99b421de",
  "actual":   "18cac4b7219d1b68ba5100a0ddab9cd321ae2b62605c837d089546e23ee5d795" }
```
✅ El mecanismo de evals re-verifica el hash antes de correr y caza el drift.

Caso B — **property-tests (`tests_sha256`), sandbox (`require_test_approval` NO set)**: copia
en temp, ablando el oráculo (`self.assertEqual(size, OPCODES_ORACLE[op])` → `pass  # TAMPER`)
sin re-firmar → **NO detectado, gate PASS**:

```
raw-bytes hash original : cdf60f86f46822a9cd1201b7719e1e524846a18f70ad3caee8c9a4da3914f8ad
raw-bytes hash tampered : 7ce4ff1e47fb8b33de50d488219a4d978b6064e7790b667c1a7698b154323c49
stored tests_sha256      : c339d9cff0ae59b4... (semántico; no verificado — require_test_approval ausente)
--- task_gate rc 0
{ "verdict": "PASS", "stage": "all", "function": "decode_instruction", ... }
```
❌ El implementador ablandó el test y obtuvo PASS. El hash firmado ni se consultó.

Caso C — **mismo sandbox, tests intactos, sólo prendo `require_test_approval: true`**: el gate
rechaza aunque **no** haya tamper, porque el hash firmado (semántico, `c339d9…`) != el que
calcula el gate (crudo, `cdf60f…`). Re-firmar con `approve_tests.py` re-escribe el mismo
semántico y **sigue rechazando**. (Salida en hallazgo CRÍTICO #1.)

Conclusión del tamper: `cases_sha256` cumple la promesa; `tests_sha256` no — ni congela por
default (Caso B) ni se verifica consistentemente cuando se prende (Caso C).

---

## Cosas que están BIEN

- **`cases_sha256` end-to-end**: `approve_eval_cases.py:42` y `eval_gate.py:37-39,53-66` usan
  el mismo `dataset_digest` (sha256 LF-normalizado → portable CRLF). Tamper detectado (Caso A).
  LF-normalización bien pensada para multi-OS.
- **Ed25519 en `ccdd.py` correcto**: `verify_attestation` (`:74-81`) atrapa `InvalidSignature`
  **y** `ValueError` (hex malformado/firma vacía → `False`, no bypass). `valid_signers`
  (`:84-96`) exige: clave pública del revisor en `reviewers.json`, `content_sha256 == hash` **y**
  firma válida. Firma ausente/vacía → no suma signer. `_attest_msg` (`:64-65`) liga la firma a
  `slot:hash` (no replicable a otro slot). R6/R7 fail-closed sin firmas válidas
  (`_emit_attestation_verdict:688-694`, `check_r7_reviewers:762-765`).
- **R6/R7/R8/R9 bloquean debilitamiento**: quitar guardrail, bajar `on_fail`, bajar
  `review_quorum`, o quitar `sign: true` → exit 1 (verificado por `tests/test_l2_governance.py`,
  15/15 ok).
- **`expected-hashes.json` internamente consistente**: firma y verificación usan
  `semantic_hash` ambos lados (`ccdd.py:129` vs `:136-139`); drift → error R4.
- **`eval_checks` robusto a output no-dict**: `run_checks:109-110` y `check_schema:27-28`
  devuelven violación dura controlada en vez de `AttributeError` (test `non_dict_output_fails_gracefully`).
- **Schema ausente declarado → INVALID explícito** (`eval_gate.py:85-87`): no degrada en silencio
  ante un typo en la ruta del schema.
- **`mutation_audit` bien implementado cuando se corre**: supervivientes reportados, timeout/crash
  no sobreviven, restauración byte-exacta del target, exclusión de `return None` literales.
- **`judge_openai` fail-closed** (`eval_judge.py:52-53`): error de red/timeout → veredicto `fail`
  → `judge_audit` lo cuenta como desacuerdo (no tumba, pero no falsea acuerdo).

---

## Limitaciones de mi auditoría

- No ejercité el flujo `request_human_attestation → review_attestations → complexity_gate`
  end-to-end contra el repo (es interactivo `input()` y escribiría `contracts/…/attestations.json`);
  leí la lógica estática (`complexity_gate.py:61-74`, `review_attestations.py:55-59`) — la
  ausencia de `verify_attestation` es inequívoca.
- No corrí `judge_audit --provider openai` (no hay endpoint/modelo configurado); la conclusión
  sobre el default `stub` se basa en el código + la corrida real con stub.
- No muté slots `.py` reales (no existen en los contratos) para demostrar el hallazgo MEDIO de
  divergencia attest/R6; es análisis de código.
- `mutation_audit` lo leí y validé su mecánica con los tests del repo (`test_mutation_audit.py`),
  no corrí mutaciones nuevas.
- El tamper de tests se hizo sobre `examples/sandbox` y `examples/batch/popcount` en copias
  temporales fuera del repo; no se modificó ningún archivo versionado.