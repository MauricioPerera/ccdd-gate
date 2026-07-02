# R1 — Reparación de checks AST (falsos negativos + falsos positivos)

Ronda de auditoría R1 sobre los 6 checks antipatrón del gate CCDD. Se arreglaron los falsos negativos
(FN: el check no caza patrones reales) y los falsos positivos por función anidada (FP: antipatrones
de funciones/lambdas internas se atribuían al target). Solo se tocaron los archivos autorizados.

## Archivos editados

Runners (6): `runners/deps_check.py`, `runners/purity_check.py`, `runners/mutdef_check.py`,
`runners/bareexcept_check.py`, `runners/assert_check.py`, `runners/nonecmp_check.py`.
Tests (6 check + 6 gate): los `tests/test_*_check.py` y `tests/test_*_gate.py` correspondientes.
No se tocó `task_gate.py`, `tc_lint.py`, `complexity_mcp.py`, `orchestrator.py` (otros devs).

## Bugs arreglados

### 1. deps_check — FN: imports dinámicos no detectados
`_imported_modules` sólo veía `import`/`from ... import` estáticos. Añadido `_dynamic_imports` que
caza `__import__("x")`, `importlib.import_module("x")` y `import_module("x")` (vía
`from importlib import import_module` / alias). Si el arg es un string literal, el módulo se somete a
`deps_allowed`/stdlib igual que un import estático (top-level). Si el arg no es literal, se reporta
`"importlib"` como mecanismo no resoluble; como `importlib` es stdlib, el filtro de `allowed` lo
descarta salvo que el caller lo retire explícitamente (evita FP sobre imports dinámicos legítimos de
stdlib). Decisión documentada en el docstring.

### 2. purity_check — FN: _DENYLIST sólo nombres planos
Añadida detección de `ast.Call` por atributo (`_attr_call_mark`):
- attrs peligrosos sin importar receptor: `system, popen, Popen, check_output, write_text,
  write_bytes, read_text, urlopen`.
- módulos donde cualquier método es I/O: `shutil`, `socket`.
- attrs restringidos a su módulo (evita FP): `os.{system,popen}`, `subprocess.{run,call,Popen,
  check_output}`, `sys.write` (sys.stdout/stderr.write), `requests.{get,post,...}`.
Así `dict.get` (receptor ≠ `requests`) NO se marca; `requests.get` sí. Marca devuelta = nombre del
attr (consistente con el `func.id` de los Name calls).

### 3. mutdef_check — FN: sólo {list,dict,set}
Añadido: `bytearray()`, `collections.defaultdict/deque/OrderedDict()` (vía atributo o `from
collections import X`), `dict.fromkeys(...)`, y `<receptor mutable>.copy()` (receptor = literal
List/Dict/Set o Call a fábrica mutable, incluyendo cadenas como `dict.fromkeys(k).copy()`).
`frozenset()`/`tuple()` y `frozenset().copy()` NO se marcan (inmutables).

### 4. bareexcept_check — FN: `except ():` (tupla vacía)
`except ():` atrapa todo igual que `except:` pero `h.type` es `ast.Tuple` con `elts==[]`, no `None`.
`_is_bare` trata ahora `type is None` O `Tuple` con `elts==[]`.

### 5. FP por función anidada (assert, nonecmp, bareexcept, purity)
Estos checks usaban `ast.walk(fn_node)`, que desciende en `FunctionDef`/`AsyncFunctionDef`/`Lambda`
anidados y atribuía sus antipatrones al target exterior. Sustituido por un helper `_walk_local` que
recorre el cuerpo del target SIN descender en defs/lambdas internas (en purity, `_collect_marks`
además salta los stmts que son def/lambda). Los bloques anidados no-función (if/for/try/…) siguen
contando. `metrics.py` (complejidad ciclomatica, que mide anidadas a propósito) no se tocó.
`mutdef` no necesitaba el fix: sólo inspecciona `fn.args` (la firma), no el cuerpo.

## Tests añadidos (todos fallan con código viejo, pasan con el fix; + guards de FP)

- `test_deps_check.py`: 8 tests (importlib.import_module literal, `__import__` literal,
  `from importlib import import_module` + alias, stdlib/allowed no flaguea, no-literal no flaguea,
  dotted top-level).
- `test_purity_check.py`: 16 tests (os.system/popen, subprocess.run/check_output, sys.stdout.write,
  pathlib write_text, requests.get, urllib.urlopen, shutil.*, socket.*, dict.get no FP, obj.call no
  FP, nested print/os.system no atribuidos).
- `test_mutdef_check.py`: 14 tests (bytearray, collections defaultdict/deque/OrderedDict por attr y
  por Name, dict.fromkeys, .copy() sobre literal/factory/fromkeys-chain, frozenset/tuple/frozenset
  .copy() no marcados).
- `test_bareexcept_check.py`: 3 tests (`except ():` bare, tupla no-vacía ok, nested bare no
  atribuido).
- `test_assert_check.py`: 2 tests (nested assert no atribuido; assert en bloque if sí cuenta).
- `test_nonecmp_check.py`: 2 tests (nested `== None` no atribuido; `!= None` en bloque if sí cuenta).

## Suite final

```
cd "D:\repos\Nueva carpeta (38)\ccdd-gate" && python -m unittest discover -s tests
```
Corrida 1: `Ran 399 tests in 9.382s` — `OK` (0 failures, 0 errors).
Corrida 2: `Ran 399 tests in 8.468s` — `OK` (0 failures, 0 errors).

## Trade-offs / notas

- **Detección de imports dinámicos no literales**: a propósito NO se flaguea (importlib es stdlib).
  Es un trade-off a favor de cero FP sobre imports dinámicos legítimos; el gancho queda para el caso
  teórico en que `importlib` se retire de `allowed`.
- **`.write_text`/`.read_text`/etc. se marcan sin mirar receptor**: cualquier `.write_text()` se
  considera I/O (pathlib). Riesgo de FP marginal si una clase de usuario define un `write_text` no
  de I/O; aceptable dada la fuerte correlación con pathlib.
- **`socket`/`shutil` cualquier método**: marca cualquier `socket.*`/`shutil.*` (no hay attrs
  seguros en esos módulos que sean comunes y no-I/O).
- **Flakiness observada (NO causada por R1)**: durante la sesión aparecieron fallos transitorios en
  `test_orchestrator_cefl.py`, `test_mcp_security.py`, `test_measure.py` (archivos WIP no tracked de
  otros devs) y mods paralelas a `orchestrator.py`/`measure.py`/`complexity_mcp.py`. Esos fallos
  aparecen también con mis cambios stashados (estado inconsistente por stash de tracked + untracked
  de otros devs) y no tocan los archivos de R1. Al estabilizarse el WIP paralelo, 5 corridas
  consecutivas + las 2 finales quedaron en verde. Mis 12 archivos de test son deterministas (127
  check + 65 gate, todos OK).