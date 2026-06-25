---
task: impure-operations
intent: "Listar las operaciones impuras presentes en el cuerpo de una función."
target: ../../../runners/purity_check.py
signature: "def impure_operations(source: str, fn_name: str, target_line: int = None) -> list"
test_command: "python -m unittest tests.test_purity_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 9, nesting_max: 3, params_max: 3, lines_max: 30 }
deps_allowed: []
forbids: ["__import__", "estado global", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_purity_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver la
lista ordenada y sin duplicados de las "marcas" de impureza halladas en el cuerpo de esa función.
Vacío = pura. Base de un gate que exige pureza en funciones declaradas puras.

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: list[str]  ORDENADA y SIN duplicados de marcas de impureza del CUERPO de la función:
 - "print", "open", "input", "eval", "exec", "__import__"  -> si hay una llamada a ese nombre
 - "global"   -> si hay una sentencia `global`
 - "nonlocal" -> si hay una sentencia `nonlocal`
 - "import"   -> si hay un `import`/`from ... import` DENTRO de la función
 resultado = sorted(set(marcas))
error: si `source` no parsea, o la función no existe -> devolver [] (lista vacía).
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Salida ordenada ascendentemente y sin duplicados.
- Solo mira el CUERPO de la función objetivo (no otras funciones del módulo).
- Función ausente o source no parseable -> [] (no lanza).

## Examples
- `impure_operations("def f(x):\n    return x + 1", "f")` -> `[]`
- `impure_operations("def f(x):\n    print(x)\n    return x", "f")` -> `["print"]`
- `impure_operations("def f(x):\n    print(x)\n    open('a')", "f")` -> `["open", "print"]`
- `impure_operations("def f(x):\n    global G\n    return x", "f")` -> `["global"]`
- `impure_operations("def f(x):\n    import os\n    return os", "f")` -> `["import"]`

## Do / Don't
- DO: `ast.parse`; localizar la def de `fn_name` (honra target_line); recorrer su cuerpo buscando
  Call a nombres del denylist, sentencias Global/Nonlocal e Import/ImportFrom.
- DON'T: ejecutar el código; usar `__import__`; abrir archivos; mirar otras funciones del módulo.
- Patrón a imitar: `_find_function` de `runners/sig_check.py`.

## Tests
`tests/test_purity_check.py`: oráculo independiente con casos fijos (source -> lista esperada a
mano). No importa nada del target salvo `impure_operations`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/purity_check.py`.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz (extrae sub-funciones
  auxiliares en el mismo archivo; el gate solo mide `impure_operations`).
