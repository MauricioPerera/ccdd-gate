---
task: none-cmp
intent: "Listar las líneas que comparan con None usando ==/!= en una función."
target: ../../../runners/nonecmp_check.py
signature: "def none_eq_lines(source: str, fn_name: str, target_line: int = None) -> list"
test_command: "python -m unittest tests.test_nonecmp_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 10, nesting_max: 3, params_max: 3, lines_max: 30 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_nonecmp_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver los
números de línea donde se compara con `None` usando `==` o `!=` (antipatrón; debe usarse `is`/`is not`).
Base de un gate.

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: list[int]  ORDENADA de líneas de cada ast.Compare del cuerpo cuyo operador sea Eq o NotEq y
     que tenga un operando (left o cualquier comparator) que sea Constant con valor None.
 - `x == None` / `x != None` / `None == x` -> cuenta
 - `x is None` / `x is not None`           -> NO cuenta (operador Is/IsNot)
 - `x == 1`                                -> NO cuenta
error: si `source` no parsea o la función no existe -> devolver [] (lista vacía).
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Salida ordenada ascendentemente y sin duplicados.
- Solo mira la def objetivo (honra target_line).
- Función ausente o source no parseable -> [].

## Examples
- `none_eq_lines("def f(x):\n    return x == None", "f")` -> `[2]`
- `none_eq_lines("def f(x):\n    return x is None", "f")` -> `[]`
- `none_eq_lines("def f(x):\n    return None == x", "f")` -> `[2]`

## Do / Don't
- DO: `ast.parse`; localizar la def (honra target_line); recorrer su cuerpo buscando `ast.Compare`
  con `ast.Eq`/`ast.NotEq` en `ops` y algún operando `ast.Constant(value=None)`.
- DON'T: ejecutar el código; contar `is`/`is not`; `__import__`; `print`; abrir archivos.
- Patrón a imitar: `_find_function` de `runners/sig_check.py`.

## Tests
`tests/test_nonecmp_check.py`: oráculo independiente con casos fijos. No importa nada del target
salvo `none_eq_lines`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/nonecmp_check.py`.
- Mantené nesting <= 3 (el repo-gate mide todo el código); extrae sub-funciones si hace falta.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz.
