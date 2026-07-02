# A5 — Auditores project-wide e integración GitHub — Auditoria

Fecha: 2026-07-01 · Auditor: read-only · Python: 3.14.6 · Repo en `main` (HEAD 15488e2)

## Resumen

Audité los 3 auditores project-wide, la capa de integración GitHub (`ci_gate`, `reporter`,
`scaffold`, `lifecycle`, `decompose`, `link`), `nm_gate`, `rules_gate`, `repo_gate`,
`tree_shaker` y los dos workflows. Corrí los 3 auditores sobre el propio repo y la suite de
tests de integración (66 tests OK) + tests de auditores/rules_gate (23 tests OK).

**No hay command injection en la capa GitHub.** Todos los `subprocess.run` son lista-form,
cero `shell=True`, el token va por `env` (no por CLI ni log). Esto es lo que más me preocupaba
y está bien.

Los hallazgos reales son de **correctitud de auditores** (falsos +/- documentados o no), un
**crash de `rules_gate` con YAML roto** que contradice su propio contrato de exit codes, y un
**problema funcional en CI para PRs de fork**: el `--post` falla con token read-only y su
excepción **no está envuelta**, de modo que un fallo de posting pisa el veredicto del gate
(exit 1 sin importar si el gate pasó). Severidad máxima: ALTO (no CRÍTICO).

| Sev  | # | Título |
|------|---|--------|
| ALTO | 1 | `ci_gate`: fallo de posting (`--post`) pisa el veredicto del gate; PRs de fork siempre rojos |
| ALTO | 2 | `rules_gate`: YAML inválido crashea con traceback (exit 1) en vez de INVALID (exit 2) |
| MEDIO| 3 | `audit_composition`: falso positivo — `from pkg.helper import util` marca composición con `util.py` |
| MEDIO| 4 | `audit_annotations`: falso negativo — anotaciones string forward-ref (`x: "Node"`) no se cazan |
| MEDIO| 5 | `audit_orphan_targets`: 50 huérfanos sobre el propio repo (fixtures/examples/scripts no exentos) |
| MEDIO| 6 | `audit_composition`: falso negativo por matching de stem superficial + colisión de stems |
| BAJO | 7 | `reporter`/`decompose`: idempotencia frágil (TOCTOU, marcadores duplicados, colisión de slug) |
| BAJO | 8 | CI ejecuta código de test controlado por el PR con `GITHUB_TOKEN` en `env` (mitigado en forks) |
| BAJO | 9 | `repo_gate`: excepciones no capturadas en `extract_source`/`read_text` crashean el gate |

## Hallazgos

### [SEV: ALTO] 1 — `ci_gate`: un fallo de posting pisa el veredicto del gate (PRs de fork siempre rojos)
- Archivo: `integrations/github/ci_gate.py:171`, `:182-185`; workflow `.github/workflows/ccdd-gate.yml:38-45`
- Descripción: `main()` hace `print(body)` luego `_maybe_post(a, body)` **sin try/except**
  (`ci_gate.py:171`). `_maybe_post` llama a `reporter.upsert_comment` → `_gh_json` que, si `gh`
  falla, `raise RuntimeError(...)` (`reporter.py:81`). Esa excepción propaga fuera de `main` y el
  proceso termina con traceback/exit 1 **antes** de llegar a `return 0 if ok else 1`
  (`ci_gate.py:172-173`). O sea: el exit code lo decide el posting, no el veredicto del gate.
- Impacto: en el workflow, `--post` siempre está encendido y `GH_TOKEN: ${{ github.token }}`.
  Para PRs **de fork**, el `GITHUB_TOKEN` del evento `pull_request` es **read-only** para
  `pull-requests: write` (comportamiento documentado de GitHub). Resultado: el `POST`/`PATCH`
  del comentario falla en TODO PR de fork → el check `ccdd-gate` queda rojo **independientemente
  del veredicto real**. Un PR externo que cumple el gate igual falla CI. Además, como el job no
  tiene filtro de paths (correcto, para required-check), esto afecta a todo fork PR.
- Repro (salida real): no reproducible sin un fork real + Actions, pero la cadena estática es
  concluyente: `_maybe_post` no envuelve `upsert_comment`, y `upsert_comment` levanta en error
  de `gh`. Simulación local de la misma ruta:
  ```
  >>> reporter._gh_json("api", "--method","POST","repos/x/y/issues/1/comments","-f","body=z")
  RuntimeError: gh falló: ...   # propaga fuera de ci_gate.main -> exit 1
  ```
- Fix sugerido: envolver `_maybe_post` en `try/except RuntimeError` y **logear a stderr sin
  cambiar el exit code**; el veredicto del gate (no la capacidad de comentar) debe decidir el
  exit. Alternativa: publicar con un PAT/`pull_request_target` + workflow separado para
  comentarios (pero eso reintroduce el riesgo de fork-write; mejor sólo aislar el exit code).

### [SEV: ALTO] 2 — `rules_gate`: YAML inválido crashea con traceback (exit 1) en vez de INVALID (exit 2)
- Archivo: `runners/rules_gate.py:66` (`_load_rules`), `:103` (política de exit)
- Descripción: el docstring declara `Exit: 0 sin violaciones · 1 violaciones · 2 config inválida`
  (`rules_gate.py:11`). `_load_rules` valida tipo-lista, `check`/`files` presentes y `check`
  conocido (`:67-73`) —esos casos sí retornan `(None, err)` y `gate` devuelve `INVALID`
  (`:79-80`) → exit 2 correcto. **Pero** `yaml.safe_load(...)` (`:66`) está fuera de cualquier
  try: un `rules.yaml` con **sintaxis YAML rota** (no semántica) lanza `yaml.ScannerError` sin
  capturar → traceback → exit 1. El caller (CI/`nm_gate`) lo lee como "violación" (FAIL), no
  como "config inválida".
- Impacto: un typo en `rules.yaml` (indentación, `:` mal puesto) se reporta como FAIL del gate
  con un traceback espantoso en vez de un mensaje limpio + exit 2. Confunde al operador y
  rompe el contrato documentado de exit codes. Si `nm_gate` lo consumiera como `commands.test`,
  un YAML roto se interpretaría como "el repo no pasa" en vez de "la config no sirve".
- Repro (salida real):
  ```
  $ printf 'this is: : not valid yaml [[[\n  - unclosed' > broken_rules.yaml
  $ python runners/rules_gate.py broken_rules.yaml .
  Traceback (most recent call last):
    File "runners/rules_gate.py", line 107, in <module>
      sys.exit(main())
    ... yaml.scanner.ScannerError: mapping values are not allowed here
  ---EXIT:1---     # prometido: 2
  ```
- Fix sugerido: `try: data = yaml.safe_load(...) except yaml.YAMLError as e: return None,
  f"rules.yaml mal formado: {e}"` en `_load_rules`. Mismo tratamiento para `Path.read_text`
  (MissingFile) y `yaml.safe_load(None)` (archivo vacío → `None` → ya cae al check de
  `isinstance(data, list)`, OK).

### [SEV: MEDIO] 3 — `audit_composition`: falso positivo por `from pkg.helper import util`
- Archivo: `runners/audit_composition.py:48-53` (`_imported_stems`), `:100` (matching)
- Descripción: `_imported_stems` añade a `stems` tanto el último componente del módulo **como
  cada nombre traído por `from x import y`** (`:51-52`). Luego `composes = ... s in
  _imported_stems(tgt) and s in funcs` (`:100`) compara esos stems contra los stems de los
  targets. Si un contrato importa **un nombre** que se llama igual que el **stem** de otro
  target, lo marca como composición aunque sea coincidencia nominal.
- Impacto: ruido y falsa "deuda de composición". El auditor no distingue "importar el módulo
  `util`" de "importar un símbolo llamado `util` desde otro módulo".
- Repro (salida real, repo sintético en tmp):
  ```
  main.py:  from pkg.helper import util   # importa el SÍMBOLO util, no el módulo util.py
  imported_stems of main.py: {'helper', 'util'}
  ungated_composition: [{'contract': 'main.md', 'composes': ['util'], 'behavior_verified': True}]
  => main.py flagged as composing util? True
  ```
- Fix sugerido: para `ImportFrom`, registrar el módulo de origen y resolver el target por
  ruta relativa (no por stem del nombre importado). Como mínimo, distinguir `import x`
  (módulo) de `from a import b` (símbolo `b`) y no comparar `b` contra stems de targets de
  módulo. Documentar la limitación si no se arregla.

### [SEV: MEDIO] 4 — `audit_annotations`: falso negativo con anotaciones string forward-ref
- Archivo: `runners/task_gate.py:266-281` (`_annotation_name_refs`), usado por
  `runners/audit_annotations.py:32`
- Descripción: `_annotation_name_refs` sólo cuenta `ast.Name` dentro de las anotaciones
  (`task_gate.py:280`). Una anotación **string** (`x: "UndefinedNode"`, `-> "Missing"`) es un
  `ast.Constant`, no un `ast.Name`, así que **no se reporta** aunque el nombre no esté
  importado/definido. El propio docstring lo admite: *"Las forward-refs en string NO se
  incluyen"* (`task_gate.py:268`).
- Impacto: éste es **exactamente** el bug que el auditor dice cazar ("nombres usados en
  anotaciones sin importar/definir … rompen en <Py3.14"). Las anotaciones string son la forma
  más común de forward-ref y **la que peor rompe en runtime <3.14** (NameError al evaluar la
  string). El gate las deja pasar en silencio → falso negativo que subestima el riesgo que
  pretende surfacar. Es una limitación **documentada**, pero socava el propósito del auditor.
- Repro (salida real):
  ```
  src: def f(x: "UndefinedNode") -> "Missing": return x
  annotation refs: set()        # <- debería contener UndefinedNode, Missing
  defined: {'f'}
  gate_annotations result: None   # PASS silencioso
  => string-fwd-ref undefined name CAUGHT? False
  ```
- Fix sugerido: cuando una anotación sea `ast.Constant` de `str`, hacer `ast.parse(valor,
  mode='eval')` y extraer los `Name` de ese sub-árbol (con el mismo `defined`/`builtins`).
  Mismo tratamiento para `ast.parse` sobre strings de `typing.get_type_hints`-style. Sigue
  siendo determinista y zero-dep.

### [SEV: MEDIO] 5 — `audit_orphan_targets`: 50 huérfanos sobre el propio repo (soporte no exento)
- Archivo: `runners/audit_orphan_targets.py:22` (`_SKIP`), `:25-31` (`_is_excluded`)
- Descripción: `_SKIP = {".git",".pytest_cache","__pycache__","node_modules","tests"}` y
  exime por nombre `__init__.py`, `conftest.py`, `test_*` (`:31`). **No** exime
  `fixtures/`, `examples/`, `benchmarks/`, `scripts/`, `integrations/`. El docstring lo
  asume: "Para CI de proyectos construidos ENTERAMENTE con CCDD" (`:9`) y aclara que **no**
  se cablea al ci_gate del propio repo (`:10-11`). Correcto por diseño para un repo 100%
  CCDD —pero cualquier repo mixto (la mayoría) grita.
- Impacto: correrlo sobre ccdd-gate mismo → **50 huérfanos**, todos código legítimo de
  soporte (runners, fixtures, examples, integrations, scripts, benchmarks). No es un bug del
  repo; es que el auditor no distingue "código que debería ser target" de "código de
  soporte/herramienta". Un consumidor que lo cablee a su CI sin un repo 100% CCDD obtiene
  ruido masivo y un exit 1 permanente.
- Repro (salida real, recortada):
  ```
  $ python runners/audit_orphan_targets.py .
  {"py_files": 65, "contracts": 28, "orphans": [
    "benchmarks\\bench_gate.py","ccdd.py","examples\\eval\\...\\support_bot.py",
    "fixtures\\complex_sample.py","fixtures\\conformance\\python\\*.py" (7),
    "integrations\\github\\*.py" (6),"integrations\\no-mistakes\\nm_gate.py",
    "runners\\*.py" (~30),"scripts\\smoke_run_ephemeral_agent.py", ... ], "ok": false}
  ---EXIT:1---
  ```
- Fix sugerido: añadir `fixtures`, `examples`, `benchmarks`, `scripts` a `_SKIP` **o** (mejor)
  hacer el conjunto de directorios exentos configurable (p.ej. `orphan_skip_dirs` en el
  front-matter del repo o un arg CLI), porque qué cuenta como "código de implementación" varía
  por proyecto. Hoy la lista es hardcodeada y angosta.

### [SEV: MEDIO] 6 — `audit_composition`: falso negativo por matching de stem superficial + colisión de stems
- Archivo: `runners/audit_composition.py:95` (dict `funcs` key por stem), `:100` (matching)
- Descripción (colisión): `funcs[Path(fm["target"]).stem] = ...` (`:95`) es **last-wins**. Dos
  targets con el mismo stem (p.ej. `aacs/schema.py` y `b/schema.py`, ambos stem `schema`)
  colisionan: sólo el último se rastrea; la composición hacia el primero se pierde.
- Descripción (matching superficial): `composes` se arma con `s in _imported_stems(tgt)`
  donde los stems son el último componente del módulo o los nombres de `from`. `import aacs`
  y luego `aacs.schema.parse()` produce sólo el stem `aacs` —si el target es `aacs/schema.py`
  (stem `schema`), **no** se detecta composición. Se necesita que el import exponga el stem
  exacto del target.
- Impacto: deuda de composición real no surficada (falso negativo) en proyectos con paquetes
  anidados o targets homónimos en distintos dirs.
- Fix sugerido: keyear `funcs` por **ruta relativa normalizada**, no por stem; y resolver
  composición por la ruta del módulo importado (relativa a `root`), no por coincidencia de
  stem suelto.

### [SEV: BAJO] 7 — `reporter`/`decompose`: idempotencia frágil (TOCTOU, marcadores, slug)
- Archivo: `integrations/github/reporter.py:85-95`; `integrations/github/decompose.py:57-74`
- Descripción:
  - `reporter.upsert_comment` hace GET de comentarios → busca marker → PATCH o POST
    (`:87-95`). Entre el GET y el POST hay una **ventana TOCTOU**: dos corridas concurrentes
    (p.ej. dos pushes rápidos) pueden ambas ver "sin marker" y POST dos comentarios marcados.
    Re-ejecutar entonces actualiza **sólo el primero** (`find_marked_comment` devuelve el
    primero, `reporter.py:73`) y el segundo queda **drift** (veredicto viejo para siempre).
  - `decompose.find_existing` busca `<!-- ccdd-task:{slug} -->` en el body (`:59-63`). Si dos
    contratos comparten el campo `task` (mismo slug), el segundo se **skip** como "existente"
    erróneamente (`:71-73`). Si un humano edita el body del sub-issue y borra el marker, la
    próxima corrida **duplica** el sub-issue.
  - `ci_gate.combined_report` elimina markers internos con `.replace(reporter.MARKER + "\n",
    "")` (`ci_gate.py:141`). Si un `render` individual deja el marker **sin `\n`** siguiente,
    no se strippea → marker duplicado en el body → mismo problema de drift en upsert.
- Impacto: no es seguridad; es ruido/deriva de comentarios y sub-issues. Marcadores HTML en
  bodies son frágiles por construcción (cualquiera con write al issue los puede romper).
- Fix sugerido: para `reporter`, hacer el upsert **atómico** vía un comentario **dedicado por
  contrato** identificado por una clave estable (p.ej. hash del contract path) en vez de un
  marker escaneable; o tolerar N marcados actualizando todos. Para `decompose`, validar
  unicidad del slug antes de plan y usar la API de sub-issues + `issue:` del contrato como
  fuente de verdad (no el body).
- Nota: los **núcleos puros** (`label_transition`, `diff_labels`) sí son idempotentes y
  testeados (`tests.test_lifecycle`, `tests.test_issue_link`); el problema es la capa online.

### [SEV: BAJO] 8 — CI ejecuta código de test controlado por el PR con `GITHUB_TOKEN` en `env`
- Archivo: `.github/workflows/ccdd-gate.yml:23-25` (checkout PR head, `pull_request`),
  `:38-39` (`GH_TOKEN` en env); `runners/task_gate.py:77` (`subprocess.run(cmd, ...)` corre los
  property-tests del contrato)
- Descripción: el workflow usa `on: pull_request` (no `pull_request_target`) + `checkout@v4`
  del head del PR —correcto desde el punto de vista de no otorgar token de escritura al fork.
  Pero el gate **ejecuta los property-tests** que vienen en el PR (`task_gate._gate_run_tests`,
  `task_gate.py:77`), con `GH_TOKEN` (el `GITHUB_TOKEN`) presente en el `env` del proceso.
  Un PR malicioso podría shippear un "test" que lee `os.environ['GH_TOKEN']` y lo exfiltra
  por red.
- Impacto: mitigado en la vía relevante: para **fork PRs** el `GITHUB_TOKEN` es **read-only**
  (ver hallazgo 1), así que el daño se acota a lectura. Para PRs de colaboradores (own
  branches) el token es write, pero ese código es de gente de confianza. Es el riesgo
  estándar de cualquier CI que corre tests de PR; lo bajo a BAJO por la mitigación de
  fork-read-only. Sospecha no confirmada: no verifiqué si los logs del job exponen el token
  (GitHub suele mascarar secretos, pero `GITHUB_TOKEN` no es un "secret" registrado, así que
  **no se mascara** —un `print(os.environ)` en un test lo dejaría ver en el log del fork PR,
  visible al autor del fork).
- Fix sugerido: correr los property-tests en un job **sin `GH_TOKEN`** en env (separar el
  gate del posting), o en un runner aislado. Mínimo: no poner `GH_TOKEN` en el env del paso
  que corre `task_gate`; sólo inyectarlo en un paso posterior de posting.

### [SEV: BAJO] 9 — `repo_gate`: excepciones no capturadas crashean el gate
- Archivo: `runners/repo_gate.py:48` (`backend.extract_source`), `:48`/`:62` (`read_text`)
- Descripción: `_scan_file` hace `path.read_text(encoding="utf-8")` y
  `backend.extract_source(...)` sin try (`:48`). Un archivo de producción con bytes no-UTF8
  o que el backend no pueda parsear lanza y **tira todo el gate** (exit 1 con traceback en
  vez de skip del archivo). `rules_gate` sí atrapa `SyntaxError` (`rules_gate.py:49`) como
  referencia; `repo_gate` no.
- Impacto: un solo archivo problemático bloquea el dogfooding de complejidad con un crash
  opaco en vez de reportarlo y seguir.
- Fix sugerido: envolver `read_text`+`extract_source` en try y tratar el archivo como
  no-escaneable (skip + warning a stderr), manteniendo el exit code dictado por los demás.

## Resultado de correr los 3 auditores sobre el propio repo (salida real)

```
$ python runners/audit_composition.py .
{
  "functions": 27, "groups": 0,
  "ungated_composition": [], "behavior_unverified": [], "ok": true
}
---EXIT:0---        # OK

$ python runners/audit_orphan_targets.py .
{
  "py_files": 65, "contracts": 28, "ok": false,
  "orphans": [ 50 entradas: benchmarks/, ccdd.py, examples/, fixtures/ (9),
               integrations/github/ (6), integrations/no-mistakes/, runners/ (~30),
               scripts/ ]
}
---EXIT:1---        # FAIL (esperado por diseño: ccdd-gate no es 100% CCDD)

$ python runners/audit_annotations.py .
{ "checked": 14, "failures": [], "ok": true }
---EXIT:0---        # OK
```

Suite de tests (salida real):
```
$ python -m unittest tests.test_ci_gate tests.test_reporter tests.test_scaffold \
                      tests.test_lifecycle tests.test_decompose tests.test_issue_link -v
Ran 66 tests in 0.413s — OK

$ python -m unittest tests.test_rules_gate tests.test_audit_annotations \
                      tests.test_audit_composition tests.test_audit_orphan_targets -v
Ran 23 tests in 0.122s — OK
```

## Cosas que estan BIEN

- **Cero command injection en la capa GitHub.** `grep shell=True|os.system|Popen` sobre
  `integrations/` → 0 matches. Los 6 `subprocess.run(["gh", *args])` (`reporter.py:79`,
  `lifecycle.py:74`, `link.py:106`, `decompose.py:97`, `scaffold.py:84`, `ci_gate.py:72`)
  son **lista-form**: ni el título, body, labels, branch ni número del issue/PR tocan un
  shell. `gh pr create --title {title} --head {branch} --body ...` (`lifecycle.py:116-117`)
  pasa cada valor como **un arg**: `--title` consume el siguiente token como valor, así que
  un `task`/`branch` tipo `--foo=evil` se vuelve el *valor* del título, no un flag. Sin
  argument-injection.
- **Token correcto.** `GH_TOKEN: ${{ github.token }}` via `env` (`ccdd-gate.yml:38-39`), no
  por CLI ni en `run:` visible. `permissions: contents: read, pull-requests: write`
  (`:15-17`) —mínimo para comentar, sin `write-all`. No hay `secrets.*` en el workflow.
- **No `pull_request_target` + checkout de fork.** Usa `pull_request` + checkout del head
  (`:11`, `:23-25`): NO otorga token de escritura del base al código del fork. Decisión
  correcta de seguridad (a costa del problema funcional del hallazgo 1).
- **`audit_orphan_targets` no se cablea al CI propio** (`audit_orphan_targets.py:10-11`):
  evita auto-flaggear el repo, que no es 100% CCDD. Coherente.
- **`ci_gate` corre las auditorías no-opcionales como dice el README.** `main()` siempre
  corre `audit_composition` + `audit_annotations` project-wide y las incluye en `ok`
  (`ci_gate.py:163-164, 172`); `mutation_audit` acotado a los contratos del PR (`:165`).
  Composition-debt + annotation-fail + mutation-survivors **bloquean** el PR. `orphan` se
  excluye a propósito. Consistente con la doc.
- **Workflow no-bypasseable por path-filter.** `on: pull_request` sin filtro de paths
  (`ccdd-gate.yml:11`) + comentario explícito de por qué (`:8-10`): permite exigirlo como
  required check sin que quede "pending" en PRs que no tocan contracts. (Que sea *required*
  depende de branch protection, no del workflow —ver Limitaciones.)
- **Núcleos puros bien separados de los adapters `gh`.** `is_contract`,
  `contracts_for_changed`, `combined_report`, `overall_pass` (`ci_gate.py`); `render`,
  `find_marked_comment` (`reporter.py`); `decide_transition`, `label_transition`,
  `ready_refs` (`lifecycle.py`); `build_subissue`, `plan`, `find_existing`,
  `set_issue_field` (`decompose.py`); `parse_issue_ref`, `contracts_referencing`,
  `diff_labels`, `state_to_labels` (`link.py`) —todos testeables sin red y cubiertos por los
  66 tests.
- **Idempotencia de labels correcta.** `label_transition` y `diff_labels` sólo tocan labels
  `ccdd:*`/lifecycle, son reversibles, no pisan labels ajenas, y son idempotentes (testeados:
  `test_idempotent`, `test_diff_is_idempotent`, `test_reversible_swaps_only_lifecycle`).
- **`audit_annotations` es prudente con `from x import *`** (`task_gate.py:240-242, 260-262`):
  retorna `None` (no analizable) en vez de falsos positivos masivos. Y skip limpio de targets
  no-Python (`task_gate.py:285`).
- **`rules_gate` maneja bien la config *semánticamente* inválida** (check desconocido,
  falta `check`/`files`) → `INVALID` exit 2 (`rules_gate.py:70-73, 103`). El hueco es sólo
  YAML sintácticamente roto (hallazgo 2).
- **`decompose` es dry-run por defecto** y no muta contratos sin `--post`
  (`decompose.py:118-120`; `test_dry_run_does_not_mutate_contract`).

## Limitaciones de mi auditoria

- **No corrí el workflow en GitHub.** El hallazgo 1 (fork PR + `--post` read-only) se infiere
  de la cadena estática (`_maybe_post` no envuelve `upsert_comment` + comportamiento
  documentado de `GITHUB_TOKEN` en fork PRs), no de una corrida real. Sospecha no confirmada
  end-to-end.
- **No verifiqué si `GITHUB_TOKEN` se mascara en logs** de fork PR (hallazgo 8). GitHub
  mascara *secrets* registrados, pero `github.token` no lo es; un `print(os.environ)` en un
  test malicioso probablemente lo expondría. No lo reproduje.
- **No audité `tree_shaker` a fondo**: es compresión de prompt (regex por dependencias), no
  gate de corrección ni seguridad; lo leí y no encontré invariantes rotas, pero no lo
  ejercité con inputs adversariales (p.ej. dependencias cíclicas o regex catastrófico con
  muchos deps). `_compile_dep_patterns` divide en chunks de 100 para no romper el motor
  (`tree_shaker.py:69-74`) —razonable.
- **No medí performance** de `mutation_audit` en CI (`ci_gate.py:165`) sobre PRs grandes;
  es caro por construcción (corre tests por mutante) y se acota a contratos afectados, pero
  no lo cronometré.
- **`audit_orphan_targets` sobre el propio repo** da 50 huérfanos esperados (el repo no es
  100% CCDD); no es un bug del repo, lo reporto como fragilidad del auditor para consumidores
  mixtos (hallazgo 5).
- **Branch protection** (que el check `ccdd-gate` sea realmente required/no-bypasseable) es
  configuración del repo en GitHub, no código; no puedo verificarla desde acá.
- No revisé `tc_lint.split_front_matter` en sí (fuera del área A5); lo asumí correcto dado
  que los auditores dependen de él y los tests pasan.