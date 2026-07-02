# RD1 — Reparación de 3 falsos +/- en los auditores project-wide

Rama: `audit-repairs`. Aislamiento respetado: solo `runners/audit_composition.py`,
`runners/audit_orphan_targets.py`, `runners/task_gate.py` (únicamente `_annotation_name_refs` y
sus helpers), y los 3 tests nombrados. No se tocaron otros runners, `ccdd.py` ni la cadena
`gate()`/`_gate_*`.

## Qué se arregló

### 1. [MEDIO] `audit_composition` — falso positivo `from pkg.helper import util`
`_imported_stems` mezclaba en el set el stem del módulo **y** cada nombre traído por
`from x import y`. Ahora `ast.Import` aporta el stem del módulo (`x`), y `ast.ImportFrom`
aporta el stem del módulo de **origen** (`a`), **no** el símbolo `b`. Así `from pkg.helper import
util` ya no hace que `main` "componga" `util.py`. Criterio documentado en el docstring.

### 2. [MEDIO] `audit_composition` — falso negativo por colisión de stems
`funcs[stem] = ...` era last-wins: dos targets homónimos por dir (`aacs/schema.py`, `b/schema.py`)
colisionaban y se perdía uno. Ahora `funcs` se indexa por **ruta relativa del target** y un
`by_stem` auxiliar mapea stem → lista de rutas, así el matching por stem de módulo no pierde
homónimos. `composes` sigue siendo lista de stems (los consumidores `ci_gate.py`/`test_ci_gate.py`
solo la joinean; `test_ci_gate.py` la mockea). El FP del punto 1 no regresa: el matching sigue
usando solo stems de módulo.

### 3. [MEDIO] `audit_annotations` — falso negativo con forward-refs string
`_annotation_name_refs` solo contaba `ast.Name`. Una anotación string (`x: "UndefinedNode"`,
`-> "Missing"`, `List["Node"]`) es `ast.Constant[str]` y se ignoraba. Ahora el helper `_ann_names`
recorre la anotación y, por cada `ast.Constant` de `str`, la parsea con `ast.parse(valor,
mode='eval')` (helper `_ann_string_names`) y trata los `Name` del sub-árbol igual que los
directos (mismo `defined`/builtins en `_gate_annotations`). String no parseable → se ignora
(no crashea). Determinista, zero-dep. Docstring actualizado (decía que las strings NO se
incluían).

### 4. [MEDIO] `audit_orphan_targets` — dirs exentas configurables
El `_SKIP` hardcodeado gritaba 50 huérfanos sobre cualquier repo mixto. Ahora el conjunto es
configurable: arg CLI `--skip-dir DIR` (repetible, `=` o espacio, vía `_parse_args`) y variable
de entorno `CCDD_ORPHAN_SKIP_DIR` (lista separada por comas), sobre el default inalterado
(`.git`, `.pytest_cache`, `__pycache__`, `node_modules`, `tests`). `audit(root, skip_dirs=None)`
es retrocompatible; `complexity_mcp.audit_orphan_targets` la sigue llamando con un arg.

## Tests

Nuevos (fallan con código viejo, pasan con el fix):
- `CompositionSymbolVsModuleTest::test_symbol_import_not_flagged_as_module_composition` — FP pto.1.
- `CompositionHomonymCollisionTest::test_homonyms_not_lost_by_stem_collision` — FN pto.2
  (verifica `functions==3` y ambos `schema`/`schema2` flaggeados; viejo colisionaba a 2 y perdía uno).
- `AuditStringForwardRefTest` — 3 casos: string indefinida reportada, string definida no
  reportada, string anidada `List["UndefinedNode"]` reportada.
- `SkipDirConfigTest` — 3 casos: default flaggea `examples/`, `skip_dirs=["examples"]` exime,
  `CCDD_ORPHAN_SKIP_DIR=examples` exime.

Ninguno de los 430 existentes se rompió (incl. `test_gates.TestGateAnnotations` que usa
`_annotation_name_refs` vía el gate, y `test_audit_composition/annotations/orphan_targets`).

## Suite final (corrida dos veces, idéntica)

```
438 passed, 13 subtests passed in 12.78s
```
0 failures / 0 errors. (Antes: 430 tests; +8 nuevos.)

## Auditores sobre el repo

```
audit_composition: {functions:28, groups:0, ungated_composition:[], behavior_unverified:[], ok:true}
audit_annotations: {checked:14, failures:[], ok:true}
audit_orphan_targets (default): ok:false  — 50 huérfanos (runners/fixtures/examples/...: soporte legítimo, default sin cambio)
audit_orphan_targets --skip-dir runners --skip-dir examples --skip-dir fixtures --skip-dir benchmarks --skip-dir scripts --skip-dir integrations:
  {py_files:2, contracts:28, orphans:["ccdd.py","run_executor.py"], ok:false}
```
`ccdd.py` y `run_executor.py` son archivos sueltos en la raíz (no dirs): `--skip-dir` exime
directorios, no archivos — esperado y consistente con el docstring.

## Complejidad (budget: cyc≤10, nest≤3, len≤41)

| función | cyc | nest | len | |
|---|---|---|---|---|
| `audit_composition._imported_stems` | 7 | 3 | 18 | ok |
| `audit_composition.audit` | 16 | 3 | 38 | cyc preexistente (16 ya en HEAD); no la subí |
| `audit_orphan_targets._skip_dirs` | 4 | 1 | 9 | ok |
| `audit_orphan_targets._is_excluded` | 4 | 1 | 7 | ok |
| `audit_orphan_targets.audit` | 10 | 0 | 13 | ok |
| `audit_orphan_targets._parse_args` | 6 | 3 | 13 | ok |
| `task_gate._ann_string_names` | 4 | 1 | 8 | ok |
| `task_gate._ann_names` | 5 | 3 | 12 | ok |
| `task_gate._annotation_name_refs` | 9 | 3 | 17 | ok |

`audit_composition.audit` ya estaba en cyc=16 antes de RD1 (deuda preexistente, fuera del
aislamiento de este lote); mi cambio la deja en 16 (mergé el build de `by_stem` en el primer
loop para no sumar un punto).

## Trade-offs / limitaciones

- **Matching por stem de módulo**: `_imported_stems` resuelve `from a.b import c` al stem `b`.
  No resuelve la ruta real del módulo importado; si un proyecto importa `import aacs` y luego
  usa `aacs.schema.parse()`, el stem expuesto es `aacs`, no `schema`, así que un target
  `aacs/schema.py` no se detecta. Es la limitación que el reporte A5 señalaba como "matching
  superficial"; arreglarla requiere resolución por ruta relativa del módulo, fuera del alcance
  de este lote (y del aislamiento). El fix entrega los 2 bugs pedidos (FP de símbolo, FN de
  colisión) sin esa resolución.
- **Composición entre homónimos por stem**: `composes` excluye `s != own_stem`, así que un
  target que importe a un homónimo del mismo stem (raro) no se flaggea. No es el caso del
  repro (el FN era un homónimo perdido como *composer*, no como compuesto), y preserva la
  semántica original de no auto-flaggear.
- **`--skip-dir` exime dirs, no archivos sueltos**: `ccdd.py`/`run_executor.py` en la raíz
  siguen gritando. Consistente con "dirs exentas" del docstring.
- **Env `CCDD_ORPHAN_SKIP_DIR`**: separada por comas (no `os.pathsep`) para evitar ambigüedad
  cross-platform con nombres de dir.