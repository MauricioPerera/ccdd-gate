# A1 — Motor del gate — Auditoria

## Resumen
El motor determinista (task_gate.py + checks AST) es mayormente sólido en determinismo intra-versión y en la resolución de homónimos (issue #41, `target_line`). Pero la **promesa central —“el implementador no puede sobornar al arbitro”— está rota de forma trivial**: el gate mide la complejidad/antipatrones **por nombre de función sobre la `def` estática**, sin verificar que ese nombre sea lo que el test realmente ejecuta en runtime. Un implementador reasigna `f = _real` (o usa un wrapper que delega a un helper sibling) y el gate mide una cáscara trivial mientras la lógica real —compleja, impura, con defaults mutables, bare-except, asserts, imports dinámicos— vive en una función **nunca medida**. Adicionalmente, los checks AST por-función tienen falsos negativos conocidos (imports dinámicos, calls por atributo, factories de mutables, `except ()`) y la integridad de tests (`tests_sha256`) es opt-in, por lo que por defecto el implementador puede sustituir el oráculo por uno vacuo. Reproducido todo en temp fuera del repo.

## Hallazgos

### [SEV: CRITICO] Bypass maestro: reasignación del nombre target (`f = _real`)
- Archivo: runners/task_gate.py:117 (/_select_target_fn:93, _gate_complexity:114), y todos los gates por-función: _gate_signature:307, _gate_purity:330, _gate_mutdef:346, _gate_bareexcept:362, _gate_assert:378, _gate_nonecmp:394 — todos via `sig_check._find_function`/equivalentes
- Descripcion: El gate selecciona la función objetivo por **nombre** sobre los nodos `FunctionDef` del AST estático. Mide la `def f` y juzga su cuerpo. Pero Python permite reasignar el nombre después: `def f(n): return n` (trivial, lo que mide el gate) y al final del archivo `f = _real`. El test importa `f` → en runtime ejecuta `_real`. El gate mide la cáscara trivial.
- Impacto: Derrota **simultáneamente** los gates de complejidad, signature, pureza, mutable-defaults, bare-except, assert y none-cmp (todos inspeccionan el cuerpo de la `def f` estática, que está vacía de antipatrones). El código real (`_real`) puede tener cyclomatic 16, `print`, `os.system`, `except:`, `assert`, `x==None`, sin que ninguno se mida. Los tests pasan porque `f` runtime == `_real`. **PASS limpio para código que viola todo el presupuesto del contrato.**
- Repro (temp, fuera del repo):
  ```
  # rebind_target.py
  def f(n): return n          # lo que mide el gate
  def _real(n):
      x=0
      if n>0: x+=1
      ... 15 ifs ...
      return x+n
  f = _real                   # runtime f = _real
  ```
  ```
  $ python runners/task_gate.py task_rebind.md
  {"verdict": "PASS", "stage": "all", "function": "f",
   "metrics": {"cyclomatic": 1, "nesting_depth": 0, "parameter_count": 1, "function_length": 3},
   "budget": {"cyclomatic_max": 5, ...}}
  EXIT=0
  ```
  `_real` tiene cyclomatic=16 (verificado con `metrics.functions_metrics`), sobre budget 5, y nunca se mide.
- Fix sugerido: tras seleccionar la `def f`, verificar que el nombre `f` no es reasignado en scope de módulo (ningún `ast.Assign`/`ast.AnnAssign` cuyo target sea `Name("f")` posterior a la def). Alternativamente, ejecutar el test instrumentando `inspect.getsource(f)`/`f.__code__` y medir el objeto que el test realmente usa, no la def estática.

### [SEV: CRITICO] Bypass por wrapper delgado: lógica en helper sibling no medido
- Archivo: runners/task_gate.py:114-127 (_gate_complexity); runners/metrics.py:58-67 (functions_metrics mide cada FunctionDef, sin relación de containment con el target)
- Descripcion: El gate mide **solo** la función target. Un helper sibling (`g`) en el mismo archivo no se mide nunca, aunque el target sea un dispatcher de 1 línea que delegue toda la lógica a `g`. A diferencia de las funciones **anidadas** (cuyos `if` SÍ se cuentan en el cyclomatic del padre vía `ast.walk`), un sibling es invisible al gate del target.
- Impacto: Un implementador frente a un budget ajustado mueve toda la complejidad a `g` (cyclomatic irrestricto) y deja `f` como `return g(n)`. PASS. Misma mecánica esconde asserts/bare-except/none-cmp/pureza en el sibling (ver hallazgo G2).
- Repro (temp):
  ```
  # wrapper_target.py
  def g(n):  # 15 ifs -> cyclomatic 16, NO medido
      ...
  def f(n):  # cyclomatic 1, medido
      return g(n)
  ```
  ```
  $ python runners/task_gate.py task_wrapper.md
  {"verdict": "PASS", "function": "f", "metrics": {"cyclomatic": 1, ...}}  EXIT=0
  ```
  `metrics.functions_metrics` confirma `g cyc=16 lines=18`, `f cyc=1 lines=2`.
- Fix sugerido: medir la complejidad del **closure transitorio** que el target puede invocar dentro del mismo archivo (suma de cyclomatic de funciones del módulo alcanzables desde `f`), o exigir que toda función referenciada en el cuerpo de `f` tenga su propio contrato (no permitir siblings no-contratados).

### [SEV: CRITICO] Oráculo vacuo + tests sin integridad por defecto → PASS para código incorrecto
- Archivo: runners/task_gate.py:37-52 (_gate_test_approval es opt-in solo si `require_test_approval`); runners/tc_lint.py:186-195 (r_tests_frozen: solo substring `fn_name in test_text`), runners/tc_lint.py:204-226 (r_tests_assert: solo exige que exista ALGÚN assert)
- Descripcion: (a) `tests_sha256` solo se verifica si el contrato declara `require_test_approval: true`; por defecto no hay lock de integridad del test → el implementador puede editar/sustituir el archivo de tests. (b) `r_tests_frozen` solo comprueba que el substring `fn_name` aparezca en el texto del test (un comentario basta) — no exige que el test **importe o llame** al target. (c) `r_tests_assert` solo exige que exista un `assert` cualquiera (`assert True` basta). Resultado: un test `# checks f behavior\nassert True` lintea limpio y gate1 lo corre → exit 0 → PASS.
- Impacto: Con `require_test_approval` desactivado (el default), el implementador puede sustituir el oráculo por uno vacuo y obtener PASS para una implementación completamente errónea. Esto rompe la promesa “el gate decide PASS/FAIL sin LLM” — el veredicto depende del test, y el test no es de fiar.
- Repro (temp): `vac_target.py` con `def f(n): return n*999` (debería ser `2*n`); `test_vac.py` = `# checks f behavior\nassert True`:
  ```
  $ python runners/task_gate.py task_vac.md
  {"verdict": "PASS", "function": "f", "metrics": {"cyclomatic": 1, ...}}  EXIT=0
  ```
- Fix sugerido: hacer `require_test_approval` default-on (o al menos hashear siempre los tests y reportar si difieren de una baseline); en `r_tests_frozen` exigir un `from <target_module> import <fn_name>` o una `Call` a `fn_name` en el AST del test, no un substring.

### [SEV: ALTO] deps_check no detecta imports dinámicos (anti-slopsquatting derrotado)
- Archivo: runners/deps_check.py:12-22 (_imported_modules solo itera ast.Import/ast.ImportFrom estáticos)
- Descripcion: `_imported_modules` solo lee nodos `ast.Import`/`ast.ImportFrom` top-level. No ve `importlib.import_module("requests")`, `__import__("sqlalchemy")`, `from importlib import import_module; import_module("pandas")`, ni `getattr(__builtins__, "requests")`.
- Impacto: El gate de deps (anti-slopsquatting, opt-in `enforce_deps`) se bypassa con cualquier import dinámico. Un implementador trae dependencias no autorizadas sin flag.
- Repro:
  ```
  src = "import importlib\nmod=importlib.import_module('requests')\nm2=__import__('sqlalchemy')"
  >>> deps_check.unauthorized_imports(src, [])
  []   # nada flaggeado
  ```
- Fix sugerido: añadir al denylist/detección calls a `__import__`, `importlib.import_module`, `importlib.__import__`, y marcar `importlib`/`__builtins__` como sensibles cuando se usan para cargar módulos.

### [SEV: ALTO] purity_check ignora calls por atributo y nombres fuera del denylist
- Archivo: runners/purity_check.py:6 (`_DENYLIST = ("print","open","input","eval","exec","__import__")`), :25-39 (_node_mark solo marca `ast.Call` cuyo `func` es `ast.Name` en el denylist)
- Descripcion: Solo marca calls a **nombres planos** en una lista cerrada de 6. No marca `os.system(...)`, `subprocess.run(...)`, `sys.stdout.write(...)`, `requests.get(...)`, `getattr(__builtins__,'exec')('code')`, ni calls por atributo en general. Tampoco detecta I/O via `pathlib.Path.write_text`, `shutil`, etc.
- Impacto: El gate de pureza (opt-in `pure: true`) se bypassa trivialmente: toda I/O/ejecución vía atributo pasa por limpio.
- Repro:
  ```
  src = "import os,subprocess,sys\ndef f(x):\n os.system('rm -rf /')\n subprocess.run(['curl','x'])\n sys.stdout.write('pwn')\n return x"
  >>> purity_check.impure_operations(src,'f')
  []   # declarado puro
  ```
- Fix sugerido: ampliar a calls por atributo con heuristicas (atributos `system/run/write/read/exec/eval/import_module/Popen/call`, nombres de módulos conocidos de I/O), o cambiar el modelo a denylist de **módulos** importados + cualquier call a algo de esos módulos.

### [SEV: MEDIO] mutdef_check no detecta factories de mutables alternativas
- Archivo: runners/mutdef_check.py:5 (`_MUTABLE_FACTORIES = {"list","dict","set"}`), :24-30 (_is_mutable_default solo atrapa literales y Call a Name en ese set)
- Descripcion: No detecta `dict.fromkeys("abc")`, `bytearray()`, `[1].copy()`, `{}.copy()`, `collections.defaultdict(list)`, `list("abc")` (esta sí la atrapa `list`), `frozenset()` (inmutable, ok), ni cualquier Call por atributo o a nombres fuera del set de 3.
- Impacto: Falsos negativos en el gate de defaults mutables (opt-in `forbid_mutable_defaults`). `def f(x=dict.fromkeys("abc"))` comparte estado entre llamadas y no se flaggea.
- Repro:
  ```
  >>> mutdef_check.mutable_defaults("def f(x=dict.fromkeys('abc'), y=bytearray(), z=[1].copy()): ...\n", 'f')
  []
  ```
- Fix sugerido: añadir `bytearray`, `defaultdict`, `deque`, `OrderedDict` al set de factories; tratar Calls por atributo cuyo receptor sea `dict`/`list`/`set`/`collections` (`copy`, `fromkeys`, `defaultdict`) como mutables.

### [SEV: MEDIO] bareexcept_check no detecta `except ()` (tupla vacía = bare efectivo)
- Archivo: runners/bareexcept_check.py:22-26 (`h.type is None`)
- Descripcion: Solo marca `ExceptHandler` con `type is None` (`except:` literal). Un `except ():` tiene `h.type` = `ast.Tuple` vacío, no None, y semánticamente atrapa todo igual que un bare except (incluye KeyboardInterrupt/SystemExit).
- Impacto: Falso negativo del gate `forbid_bare_except`. Edición: ruido, pero `except ()` es una forma real (aún más oscura) de bare-except.
- Repro:
  ```
  >>> bareexcept_check.bare_except_lines("def f():\n try:\n  x=1\n except ():\n  pass\n", 'f')
  []   # except () NO reportado; except: sí ([4])
  ```
- Fix sugerido: tratar `ast.Tuple` con `elts==[]` como bare.

### [SEV: MEDIO] Falsos positivos: antipatrones en función anidada se atribuyen al target
- Archivo: runners/assert_check.py:22-25, runners/nonecmp_check.py:44, runners/bareexcept_check.py:22-26 (todos usan `ast.walk(fn)` que desciende en FunctionDefs anidadas)
- Descripcion: `ast.walk(fn_node)` recorre **todos** los descendientes, incluidas funciones definidas dentro del cuerpo del target. Un `assert`/`except:`/`x==None` dentro de una función helper anidada se reporta con la línea del target y cuenta contra el target.
- Impacto: Falso positivo — un helper anidamiento limpio para el target puede volar el gate de antipatrones. Asimetría con el hallazgo del wrapper: lo anidado se sobre-atribuye, lo sibling se ignora.
- Repro:
  ```
  src = "def f(n):\n def h():\n  assert False\n  if n==None: pass\n  try: pass\n  except: pass\n return n"
  >>> assert_check.assert_lines(src,'f')    # [4]   <- assert de h atribuido a f
  >>> nonecmp_check.none_eq_lines(src,'f')  # [5]
  >>> bareexcept_check.bare_except_lines(src,'f')  # [9]
  ```
- Fix sugerido: en `_assert_lines`/`_bare_handlers`/`none_eq_lines`, no descender en nodos `FunctionDef`/`AsyncFunctionDef`/`Lambda` anidados; iterar solo el cuerpo directo (o excluir sub-árboles de funciones internas).

### [SEV: MEDIO] _gate_complexity crashea (no FAIL estructurado) ante target con syntax error
- Archivo: runners/task_gate.py:117 (`metrics_backends.functions_metrics` → `ast.parse` sin try); runners/metrics.py:61
- Descripcion: Si el target tiene un error de sintaxis Y el test_command no importa/ejecuta el target (p.ej. oráculo vacuo del hallazgo de oráculo), gate1 pasa (el test corre solo) y `_gate_complexity` llama `ast.parse(src)` que levanta `SyntaxError` **no capturado**. El proceso muere con traceback. Los otros gates por-función sí capturan `SyntaxError` → `return []`/`None`, pero `_gate_complexity` no.
- Impacto: No es un PASS silencioso (Python exits 1), pero el consumidor que espera un JSON `{"verdict":...}` recibe un traceback en stderr y ningún veredicto estructurado. Inconsistencia de contrato de salida; podría confundir a un orquestador que distinga FAIL-vs-crash.
- Repro: `syn_target.py` con `return n +(` + `test_syn.py`=`assert True`:
  ```
  $ python runners/task_gate.py task_syn.md
  SyntaxError: '(' was never closed   (traceback en stderr, sin JSON)
  REAL_EXIT=1
  ```
- Fix sugerido: envolver `metrics_backends.functions_metrics(...)` en `_gate_complexity` con `try/except SyntaxError` → `{"verdict":"FAIL","stage":"gate2-complexity","detail":"target no parsea: ..."}`.

### [SEV: MEDIO] semantic_hash no es estable entre versiones de Python (excepciones de complejidad)
- Archivo: runners/semantic_hash.py:13-16 (`ast.dump(tree)` sin `include_attributes`)
- Descripcion: `ast.dump` default `include_attributes=False` (sin líneas) → estable ante reformateo dentro de una misma versión de Python. Pero el formato/contenido del dump varía entre versiones de CPython (Constantes en 3.8, type_params PEP 695 en 3.12+, cambios de AST en 3.14). Una excepción firmada (`complexity_exception` en attestations.json) calculada en 3.11 puede no validar en 3.13/3.14.
- Impacto: La ruta de `request_human_attestation` / `_is_exempt` (complexity_gate.py:61-74) puede perder una excepción legítima al cambiar el intérprete → FAIL donde se esperaba PASS-exento, o (peor si coincide por colisión) eximir algo distinto. Rompe “mismo input -> mismo veredicto” cuando el input incluye la versión de Python. No confirmado cross-version aquí (solo 3.14 disponible) → **sospecha no confirmada**.
- Fix sugerido: normalizar el dump (own serializer estable) o firmar el hash junto con la versión de Python del firmante y validar coincidencia.

### [SEV: BAJO] sig_check ignora anotaciones y defaults del implementador
- Archivo: runners/sig_check.py:42-57 (compara solo nombres de params en orden); runners/task_gate.py:307-323
- Descripcion: Por diseño ignora anotaciones y defaults. `def f(x)` vs `def f(x: Dangerous) -> Any` → match. `def f(x=[])` → match (mutable default añadida).
- Impacto: Bajo — las anotaciones falsas las caza `_gate_annotations` si el nombre no está importado; el default mutable lo caza `forbid_mutable_defaults` si está activo. Pero un implementador puede añadir defaults libremente (cambiando la firma efectiva) sin que el gate de signature lo note.
- Repro: `sig_check.signature_mismatch('def f(x=[]): return x','f','def f(x)')` → `''` (sin mismatch).
- Fix sugerido: opcional — comparar también la presencia/ausencia de defaults (no su valor) si se quiere una firma más estricta.

### [SEV: BAJO] r_tests_frozen: verificación de referencia del test es substring débil
- Archivo: runners/tc_lint.py:193 (`ctx["fn_name"] not in tp.read_text(encoding="utf-8")`)
- Descripcion: Comprueba que el nombre de la función aparezca como **substring** en el texto del test. Un nombre corto (`f`, `get`, `run`) aparece en cualquier comentario/palabra. No exige import ni call.
- Impacto: Bajo como standalone (el comportamiento real lo verifica gate1 al correr), pero combinado con el hallazgo de oráculo vacuo habilita tests que “mencionan” la función sin ejercerla.
- Fix sugerido: parsear el AST del test y exigir un `ast.ImportFrom`/`ast.Import` del módulo target o un `ast.Call` al nombre.

## Cosas que estan BIEN
- **Determinismo intra-versión**: todos los checks devuelven `sorted(...)`/`set` ordenado (deps:31, mutdef:64, bareexcept:26, assert:25, nonecmp:44, purity:62); `_gate_annotations` ordena `undefined`; `dir(builtins)` es sorted; `ast.walk` es BFS determinista; `METRIC_KEYS` fija el orden de findings. No se encontró dependencia de `PYTHONHASHSEED`, locale, timestamps ni `os.walk` en el path del gate.
- **Resolución de homónimos (#41)**: `_select_target_fn` (task_gate.py:93-110) exige `target_line` si hay >1 def del nombre, y usa `node.lineno` consistente con las `candidate_lines` que reporta → no mide el equivocado en silencio. Verificado: 2 defs `f` sin `target_line` → INVALID.
- **Cadena de gates con `or`**: short-circuit devuelve el primer fallo; PASS solo si todos los opt-in devuelven None y `_gate_complexity` devuelve PASS. No hay ruta que devuelva PASS por accidente desde un check habilitado.
- **tests_sha256 es raw-bytes** (task_gate.py:42): cuando `require_test_approval` está on, cualquier cambio de bytes del test (incl. espacios) invalida → integridad fuerte. El problema es que es opt-in (ver hallazgo).
- **`_cyclomatic` cuenta funciones anidadas** (metrics.py:32 `ast.walk(node)` desciende en nested defs): no se puede bajar el cyclomatic del target escondiendo `if`s en una función anidada. (El bypass vía sibling/rebind es distinto.)
- **Lambdas/assign-alias no bypassan**: `f = lambda...` no produce un FunctionDef medible → el gate reporta “función no está” (FAIL), no PASS engañoso.
- **Group gate** tiene `MAX_GROUP_DEPTH=10` (task_gate.py:134) y recursión `gate(child, depth+1)` → ciclos acotados.
- **Excepciones de parsing** en los checks por-función devuelven `[]`/`None` (no PASS falsos) — excepto `_gate_complexity` (ver hallazgo MEDIO).

## Limitaciones de mi auditoria
- **Cross-version de semantic_hash** no verificada: solo corrí en Python 3.14.6 (MSC v.1944). La sospecha de inestabilidad del `ast.dump` entre 3.11/3.12/3.13 vs 3.14 queda como **sospecha no confirmada**.
- **Backends tree-sitter** (metrics_treesitter.py) no auditados en profundidad: las gramáticas TS/JS/TSX no estaban instaladas aquí (`register_all()` no registró nada), así que el path multi-lenguaje no se ejercitó. Los hallazgos sobre `_find_function`/selección por nombre aplican a Python; análogos en tree-sitter probables pero no reproducidos.
- **coverage_check.py** parece no cableado en `task_gate.py` (no se importa ni se invoca en la cadena `gate()`). No es un bug de seguridad pero no audité si se usa desde otro orquestador.
- **complexity_gate.py / complexity_runner.py** (path L3 + hook PostToolUse) revisados por lectura pero no reproducidos vía CLI; el hallazgo de semantic_hash los afecta vía `_is_exempt`.
- **Flujos MCP / run_ephemeral_agent** fuera de alcance (A1 = motor determinista del gate).
- No probé path-traversal en `children` de grupos (`group_dir / child` con `..`) — fuera del modelo de amenaza del implementador (el autor del contrato controla children).