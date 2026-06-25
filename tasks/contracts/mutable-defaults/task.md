---
task: mutable-defaults
intent: "Listar los parámetros de una función cuyo valor por defecto es mutable."
target: ../../../runners/mutdef_check.py
signature: "def mutable_defaults(source: str, fn_name: str, target_line: int = None) -> list"
test_command: "python -m unittest tests.test_mutdef_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 9, nesting_max: 3, params_max: 3, lines_max: 30 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_mutdef_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver la
lista ordenada de nombres de parámetro cuyo valor por DEFECTO es mutable (el footgun clásico de
Python). Vacío = seguro.

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: list[str]  ORDENADA y sin duplicados de nombres de parámetro con default MUTABLE
mutable = el default es: literal ast.List / ast.Dict / ast.Set, O una llamada a Name en {list, dict, set}
inmutable = números, strings, None, tuplas, etc.
alineación de defaults:
 - posicionales: args.defaults aplica a los ÚLTIMOS len(defaults) de args.args.
 - keyword-only: zip(args.kwonlyargs, args.kw_defaults); kw_defaults trae None donde no hay default.
error: si `source` no parsea o la función no existe -> devolver [] (lista vacía).
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Salida ordenada ascendentemente y sin duplicados.
- Solo mira la def objetivo (honra target_line para homónimas).
- Función ausente o source no parseable -> [].

## Examples
- `mutable_defaults("def f(x=[]): ...", "f")` -> `["x"]`
- `mutable_defaults("def f(x=set()): ...", "f")` -> `["x"]`
- `mutable_defaults("def f(a=0, b='s', c=None, d=()): ...", "f")` -> `[]`
- `mutable_defaults("def f(x=0, y=[]): ...", "f")` -> `["y"]`
- `mutable_defaults("def f(*, k=[]): ...", "f")` -> `["k"]`

## Do / Don't
- DO: `ast.parse`; localizar la def de `fn_name` (honra target_line); alinear defaults a sus params
  (posicionales con `args.defaults`, kw-only con `args.kw_defaults`); marcar List/Dict/Set y Call a list/dict/set.
- DON'T: ejecutar el código; usar `__import__`; `print`; abrir archivos.
- Patrón a imitar: `_find_function` de `runners/sig_check.py`.

## Tests
`tests/test_mutdef_check.py`: oráculo independiente con casos fijos. No importa nada del target salvo
`mutable_defaults`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/mutdef_check.py`.
- Mantené el anidamiento BAJO (nesting <= 3) — el repo-gate mide TODO el código de producción.
  Extrae sub-funciones auxiliares si hace falta (el gate solo mide `mutable_defaults`).
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz.
