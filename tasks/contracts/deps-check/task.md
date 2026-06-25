---
task: unauthorized-imports
intent: "Listar los módulos importados por un código fuente que no están permitidos."
target: ../../../runners/deps_check.py
signature: "def unauthorized_imports(source: str, deps_allowed: list) -> list"
test_command: "python -m unittest tests.test_deps_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 8, nesting_max: 3, params_max: 2, lines_max: 25 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "import del código analizado"]
tests: ../../../tests/test_deps_check.py
spec_version: "0.1"
---

## Intent
Dado el código fuente de un módulo Python y la lista `deps_allowed`, devolver los nombres de módulo
top-level importados que son de TERCEROS y NO están permitidos. Es la base del enforcement de
`deps_allowed` (anti-slopsquatting): caza imports a paquetes no autorizados o alucinados.

## Interface
```
in:  source: str (código Python), deps_allowed: list[str] (paquetes permitidos)
out: list[str] ORDENADO y SIN duplicados de los módulos top-level NO permitidos
reglas:
 - import X / import X.Y.Z      -> módulo top-level = "X"
 - from X import ... (nivel 0)  -> "X"
 - from .pkg import ... (nivel>=1, relativo) -> se IGNORA (es local)
 - se IGNORAN los módulos de la stdlib (sys.stdlib_module_names) y "__future__"
 - se IGNORAN los que estén en deps_allowed
 - resultado = sorted(set(no permitidos))
error: si `source` no parsea como Python -> devolver [] (la sintaxis la valida otro gate)
```

## Invariants
- Puro y determinista: analiza el AST, NO importa ni ejecuta el código; sin I/O, sin estado global.
- Idempotente: mismas entradas -> misma lista.
- Salida sin duplicados y ordenada ascendentemente.
- Un módulo de la stdlib o presente en `deps_allowed` nunca aparece en la salida.
- Un import relativo (nivel>=1) nunca aparece en la salida.

## Examples
- `unauthorized_imports("import os\nimport requests", [])` -> `["requests"]`
- `unauthorized_imports("import requests", ["requests"])` -> `[]`
- `unauthorized_imports("from collections import OrderedDict", [])` -> `[]`
- `unauthorized_imports("import zebra\nimport apple", [])` -> `["apple", "zebra"]`
- `unauthorized_imports("from . import helper", [])` -> `[]`
- `unauthorized_imports("import a.b.c", [])` -> `["a"]`

## Do / Don't
- DO: `ast` para extraer los imports; `sys.stdlib_module_names` para la stdlib; `sorted(set(...))`.
- DON'T: importar/ejecutar el código analizado; usar `__import__`; `print`; abrir archivos; estado global.
- Patrón a imitar: el análisis AST de `runners/metrics.py` (`ast.walk`).

## Tests
`test_deps_check.py`: oráculo independiente con casos fijos (snippet -> lista esperada calculada a
mano). No importa nada del target salvo `unauthorized_imports`. Existe antes de implementar.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`, `sys`).
- NO modificar los tests ni el contrato; solo implementar `deps_check.py`.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz (extrae sub-funciones
  auxiliares en el mismo archivo si hace falta; el gate solo mide `unauthorized_imports`).
