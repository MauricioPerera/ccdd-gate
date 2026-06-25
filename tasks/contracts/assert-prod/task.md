---
task: assert-prod
intent: "Listar las líneas de las sentencias assert del cuerpo de una función."
target: ../../../runners/assert_check.py
signature: "def assert_lines(source: str, fn_name: str, target_line: int = None) -> list"
test_command: "python -m unittest tests.test_assert_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 9, nesting_max: 3, params_max: 3, lines_max: 30 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_assert_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver los
números de línea de las sentencias `assert` del cuerpo de esa función (footgun: desaparecen con
`python -O`). Vacío = ninguna. Base de un gate que prohíbe asserts en producción.

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: list[int]  ORDENADA de líneas de cada nodo ast.Assert dentro del cuerpo de la función
     (incluye asserts en bloques anidados: if/for/while/with/try del cuerpo).
error: si `source` no parsea o la función no existe -> devolver [] (lista vacía).
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Salida ordenada ascendentemente.
- Solo mira la def objetivo (honra target_line).
- Función ausente o source no parseable -> [].

## Examples
- `assert_lines("def f(x):\n    assert x\n    return x", "f")` -> `[2]`
- `assert_lines("def f(x):\n    return x", "f")` -> `[]`
- `assert_lines("def f(x):\n    if x:\n        assert x\n    return x", "f")` -> `[3]`

## Do / Don't
- DO: `ast.parse`; localizar la def de `fn_name` (honra target_line); recorrer su cuerpo recogiendo
  el `lineno` de cada `ast.Assert`.
- DON'T: ejecutar el código; usar `__import__`; `print`; abrir archivos.
- Patrón a imitar: `_find_function` de `runners/sig_check.py`.

## Tests
`tests/test_assert_check.py`: oráculo independiente con casos fijos. No importa nada del target salvo
`assert_lines`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/assert_check.py`.
- Mantené nesting <= 3 (el repo-gate mide todo el código); extrae sub-funciones si hace falta.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz.
