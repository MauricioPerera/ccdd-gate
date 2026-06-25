# GLM-REPORT — unauthorized-imports

## Qué se hizo
Implementación del cuerpo de `unauthorized_imports` en `tasks/contracts/deps-check/deps_check.py`
(stub `NotImplementedError` -> función completa). Solo se editó `deps_check.py`; `task.md` y
`test_deps_check.py` permanecen congelados e intactos.

## Implementación
- Parseo con `ast.parse`; `SyntaxError` -> `[]` (la sintaxis la valida otro gate).
- `ast.walk` para recolectar `ast.Import` y `ast.ImportFrom`.
  - `ast.Import`: top-level = `alias.name.split(".")[0]` por cada alias.
  - `ast.ImportFrom`: se ignora si `level >= 1` (relativo) o `module` falso; si no, top-level = `module.split(".")[0]`.
- Se ignoran stdlib (`sys.stdlib_module_names`), `__future__` y los presentes en `deps_allowed`.
- Salida: `sorted(set(...))` (ordenado y sin duplicados).
- Solo stdlib (`ast`, `sys`). Sin `__import__`, sin `print`, sin I/O, sin estado global, sin importar el código analizado.

Sub-funciones auxiliares en el mismo archivo (el gate solo mide `unauthorized_imports`):
- `_toplevel(name)` — split por `.` y toma el primer segmento.
- `_imported_modules(tree)` — generador que itera los top-level importados, ignorando relativos.

## Gate
Comando: `python runners/task_gate.py tasks/contracts/deps-check/task.md`

Resultado: **PASS** en el **intento 1** (sin correcciones intermedias).

### Métricas finales vs budget
| métrica        | valor | budget  |
|----------------|-------|---------|
| cyclomatic     | 4     | ≤ 8     |
| nesting_depth  | 1     | ≤ 3     |
| parameter_count| 2     | ≤ 2     |
| function_length| 8     | ≤ 25    |

Todas las métricas dentro del budget con margen amplio.