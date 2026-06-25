---
task: bare-except
intent: "Listar las líneas de los except desnudos del cuerpo de una función."
target: ../../../runners/bareexcept_check.py
signature: "def bare_except_lines(source: str, fn_name: str, target_line: int = None) -> list"
test_command: "python -m unittest tests.test_bareexcept_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 9, nesting_max: 3, params_max: 3, lines_max: 30 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_bareexcept_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y opcionalmente su línea, devolver los
números de línea de los manejadores `except:` DESNUDOS (sin tipo) en el cuerpo de esa función. Vacío
= ninguno. Base de un gate que prohíbe `except:` desnudo (antipatrón).

## Interface
```
in:  source: str (código Python), fn_name: str, target_line: int|None (desambigua homónimas)
out: list[int]  ORDENADA de líneas de los ExceptHandler con type is None (except desnudo)
 - `except:`            -> desnudo (cuenta)
 - `except Exception:`  -> tipado (NO cuenta, aunque sea amplio)
 - `except ValueError:` -> tipado (NO cuenta)
error: si `source` no parsea o la función no existe -> devolver [] (lista vacía).
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Salida ordenada ascendentemente.
- Solo mira la def objetivo (honra target_line).
- Función ausente o source no parseable -> [].

## Examples
- `bare_except_lines("def f():\n    try:\n        pass\n    except:\n        pass", "f")` -> `[4]`
- `bare_except_lines("...except ValueError:...", "f")` -> `[]`
- `bare_except_lines("def f():\n    return 1", "f")` -> `[]`

## Do / Don't
- DO: `ast.parse`; localizar la def de `fn_name` (honra target_line); recorrer su cuerpo buscando
  `ast.ExceptHandler` con `type is None`; recolectar su `lineno`.
- DON'T: ejecutar el código; usar `__import__`; `print`; abrir archivos; contar except tipados.
- Patrón a imitar: `_find_function` de `runners/sig_check.py`.

## Tests
`tests/test_bareexcept_check.py`: oráculo independiente con casos fijos. No importa nada del target
salvo `bare_except_lines`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/bareexcept_check.py`.
- Mantené nesting <= 3 (el repo-gate mide todo el código); extrae sub-funciones si hace falta.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz.
