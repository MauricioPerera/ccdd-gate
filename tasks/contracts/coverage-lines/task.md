---
task: function-lines
intent: "Listar las líneas del cuerpo de una función que la ejecución debería cubrir."
target: ../../../runners/coverage_check.py
signature: "def function_lines(source: str, fn_name: str, target_line: int = None) -> set"
test_command: "python -m unittest tests.test_coverage_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 8, nesting_max: 3, params_max: 3, lines_max: 25 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_coverage_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver el
conjunto de números de línea de las SENTENCIAS del cuerpo de esa función — las líneas que la
ejecución de los tests debería cubrir. Es el insumo del gate de cobertura.

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: set[int]  (líneas de las sentencias del CUERPO de la función; vacío si no se encuentra)
reglas:
 - EXCLUYE la línea del `def` y de los decoradores.
 - INCLUYE el lineno de cada sentencia del cuerpo (recursivamente: ifs, fors, anidadas).
 - target_line: si se da, la def cuya línea == target_line; si no, la primera de `fn_name`.
error: si `source` no parsea, o la función no existe -> devolver set() vacío.
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- La línea del `def` nunca está en el resultado.
- Mismo input -> mismo set.
- Función ausente o source no parseable -> set() (no lanza).

## Examples
- `function_lines("def f(x):\n    a = 1\n    return a", "f")` -> `{2, 3}`
- `function_lines("def f(x):\n    if x:\n        return 1\n    return 0", "f")` -> `{2, 3, 4}`
- `function_lines("def g(x):\n    return x", "f")` -> `set()` (no encontrada)
- homónimas: `function_lines("def f(a):...\n\ndef f(x):...", "f", target_line=4)` -> cuerpo de la def en L4

## Do / Don't
- DO: `ast.parse`; localizar la `FunctionDef`/`AsyncFunctionDef` de `fn_name`; recolectar `lineno`
  de las sentencias de su `body` (recursivo); excluir la línea del `def`.
- DON'T: ejecutar el código; usar `__import__`; `print`; abrir archivos; contar la línea del `def`.
- Patrón a imitar: `_find_function` de `runners/sig_check.py` (localiza la def, honra target_line).

## Tests
`tests/test_coverage_check.py`: oráculo independiente con casos fijos (source -> set esperado a
mano). No importa nada del target salvo `function_lines`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/coverage_check.py`.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz (extrae sub-funciones
  auxiliares en el mismo archivo; el gate solo mide `function_lines`).
