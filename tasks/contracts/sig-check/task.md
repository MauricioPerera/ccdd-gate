---
task: signature-mismatch
intent: "Detectar si la firma implementada difiere de la firma esperada del contrato."
target: ../../../runners/sig_check.py
signature: "def signature_mismatch(source: str, fn_name: str, expected_signature: str) -> str"
test_command: "python -m unittest tests.test_sig_check"
test_cwd: "../../.."
budget: { cyclomatic_max: 8, nesting_max: 3, params_max: 3, lines_max: 25 }
deps_allowed: []
forbids: ["__import__", "estado global", "print", "abrir archivos", "ejecutar el código analizado"]
tests: ../../../tests/test_sig_check.py
spec_version: "0.1"
---

## Intent
Dada la fuente de un módulo, el nombre de la función objetivo y la firma esperada del contrato,
devolver "" si la def implementada coincide con la esperada en nombre y nombres de parámetros
(en orden), o una descripción NO vacía del desajuste. Caza el drift de firma que rompe a los callers.

## Interface
```
in:  source: str (código Python), fn_name: str, expected_signature: str (p.ej. "def f(x: int) -> str")
out: str  ("" si coincide; descripción NO vacía si difiere o la función no está)
compara: nombre de la def == fn_name; lista ORDENADA de nombres de parámetros (posicionales,
         *args, **kwargs, keyword-only) de la impl vs la esperada.
IGNORA: anotaciones de tipo, valores por defecto y el tipo de retorno (solo nombres + orden + forma).
casos: función ausente -> NO vacío; nº/orden/nombre de params distinto -> NO vacío; *args/**kwargs
       presente en una y no en la otra -> NO vacío.
error: si `source` o `expected_signature` no parsean -> devolver una descripción NO vacía.
```

## Invariants
- Puro y determinista: analiza el AST, NO ejecuta el código; sin I/O, sin estado global.
- Coincidencia exacta de nombres de parámetros EN ORDEN (no solo la aridad).
- Anotaciones, defaults y retorno NO afectan el veredicto.
- "" si y solo si coincide; cadena no vacía en cualquier otro caso.

## Examples
- `signature_mismatch("def f(x, y): return x", "f", "def f(x, y)")` -> `""`
- `signature_mismatch("def f(x: int) -> str: ...", "f", "def f(x)")` -> `""`
- `signature_mismatch("def f(a): return a", "f", "def f(x)")` -> no vacío (nombre del param)
- `signature_mismatch("def f(y, x): ...", "f", "def f(x, y)")` -> no vacío (orden)
- `signature_mismatch("def g(x): ...", "f", "def f(x)")` -> no vacío (no encontrada)

## Do / Don't
- DO: `ast.parse` de la fuente y de la firma esperada (`expected + ":\n pass"`); comparar nombres de params.
- DON'T: ejecutar el código; usar `__import__`; `print`; abrir archivos; comparar anotaciones/defaults.
- Patrón a imitar: `_parse_sig_python` de `runners/tc_lint.py` (parsea una firma con `ast.parse`).

## Tests
`tests/test_sig_check.py`: oráculo independiente con casos fijos. Coincidencias -> `""`; desajustes
-> cadena no vacía (mensaje libre). No importa nada del target salvo `signature_mismatch`.

## Constraints
- Sin dependencias (`deps_allowed` vacío); solo stdlib (`ast`).
- NO modificar los tests ni el contrato; solo implementar `runners/sig_check.py`.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz (extrae sub-funciones
  auxiliares en el mismo archivo; el gate solo mide `signature_mismatch`).
