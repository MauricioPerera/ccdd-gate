# RE1 — Atestación: alinear el productor (`_attest_target_hash`) con el verificador (R6/R7)

## Qué cambié

**`ccdd.py` — `_attest_target_hash` (única función tocada):** reemplacé el hash
crudo `sha256(path.read_text(...))` por `semantic_hash.get_semantic_hash(text, suffix)`
en los dos `return` con contenido, exactamente el mismo cómputo que usa la
verificación R6 (`_check_r6_policy_attestation`, ~723) y coherente con R7.
Importé `semantic_hash` con import local `from runners import semantic_hash`
(idéntico a como lo hace R6). La firma de la función y el contrato de retorno
`(hash, rc)` NO cambiaron.

- Caso `__reviewers__`: sufijo `".json"` (cae al fallback crudo → hash
  byte-idéntico al anterior; R7 sigue comparando con `sha256(head_reg_raw)`).
- Caso slot estático: sufijo real del path del slot,
  `Path(slot["source"]["path"]).suffix`. Para `.py` ahora produce el
  `ast.dump` que R7/R6 esperan, en lugar del crudo que R6 rechazaría.

No toqué `cmd_attest`, R6, R7, `valid_signers` ni ningún runner.

## Bug latente cerrado

Para `.txt`/`.json` (los únicos slots hoy) `semantic_hash` cae al fallback
`sha256(content.encode("utf-8"))` == crudo, así que productor y verificador ya
coincidían. Para un slot estático `.py` (permitido por el schema) el crudo !=
semántico (`ast.dump`): `cmd_attest` guardaba un `content_sha256` que
`valid_signers` jamás aceptaría → una atestación legítima de un revisor
registrado era rechazada. El fix alinea productor ↔ verificador para todo
sufijo.

## Invariante no-op (byte-identidad para `.txt`/`.json`)

Verificada por `tests/test_attest_hash_consistency.py::TestAttestHashNoOp`:

- `_attest_target_hash(base, "system")` (`.txt`) == `hashlib.sha256(text.encode()).hexdigest()`
  == `semantic_hash.get_semantic_hash(text, ".txt")`.
- `_attest_target_hash(base, "__reviewers__")` (`.json`) == crudo == semántico.

`semantic_hash.get_semantic_hash` sólo se desvía del crudo cuando la extensión
es `.py` (y el `ast.parse` funciona); en cualquier otro caso retorna
`hashlib.sha256(content.encode("utf-8")).hexdigest()`. Por construction toda
atestación existente (slots `.txt` + `reviewers.json` `.json`) sigue validando
sin re-firmar.

## Test round-trip `.py`

`tests/test_attest_hash_consistency.py::TestAttestPyRoundTrip::test_py_critical_change_blocked_then_attested`
(reutiliza la maquinaria de `tests/test_l2_governance.py`: CLI por subprocess,
`make_pair`/`diff`/`run_ccdd`, `yaml.safe_dump`):

1. Agrega un slot estático `.py` crítico (`compaction: none`, `review_quorum: 1`)
   a base y head con contenido inicial idéntico.
2. `keygen` registra a `alice`; copia `reviewers.json` base→head (no dispara R7).
3. Modifica `pycrit.py` en head (`+1` → `+2`: cambio semánticamente distinto).
4. `diff` **bloquea** (exit 1, regresión "sin atestación") — R6 detecta el cambio
   de política crítica sin atestación.
5. `attest pycrit --reviewer alice --key ...` firma con el hash semántico.
6. `diff` **pasa** (exit 0, `rep["passed"]` true, change "ATESTADA por alice (1/1)").

Antes del fix el paso 6 fallaba: `content_sha256` (crudo) ≠ `hhash` (semántico)
→ `valid_signers` vacío → R6 sigue bloqueando. Se incluye además
`test_py_slot_matches_semantic_hash` que afirma directamente
`_attest_target_hash(<slot .py>) == semantic_hash.get_semantic_hash(text, ".py")`
y que difiere del crudo.

## Conteo final

Suite `tests/` corrida dos veces (CLI, como CI):

```
442 passed, 13 subtests passed in 13.86s   (run 1)
442 passed, 13 subtests passed in 12.57s   (run 2)
```

0 failures / 0 errors. `test_l2_governance.py` sigue 100 % verde (10 tests L2+RE1
juntos: `10 passed`). Antes: 438 tests → ahora 442 (+4 de RE1).

Nota: la colección del repo completo choca con un basename duplicado preexistente
(`examples/sandbox/test_decode_instruction.py` vs `examples/sandbox/loop_demo/...`),
ajeno a este cambio; por eso se acota a `tests/`, que es donde vive la suite de
gate (los 438 históricos).

## Trade-offs

- **Ventaja:** corrección end-to-end del ciclo de gobernanza para slots `.py`
  (los únicos en los que crudo ≠ semántico). Desbloquea atestaciones legítimas
  que hoy se rechazarían, sin tocar el verificador.
- **No-op real:** para `.txt`/`.json` el resultado es byte-idéntico; no hay
  re-firmado de atestaciones existentes.
- **Costo:** un `import` local y un `Path(...).suffix` por llamada a
  `_attest_target_hash` (trivial; sólo se invoca desde `cmd_attest`, camino
  humano-en-el-bucle, fuera del hot path del gate).
- **Riesgo residual:** si en el futuro se soportara un nuevo sufijo con hash
  semántico propio (ej. otro lenguaje en `semantic_hash`), el productor ya
  quedará alineado automáticamente con R6 porque ambos llaman a la misma
  función — que es justamente el punto de este fix.