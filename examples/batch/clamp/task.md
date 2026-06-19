---
task: clamp-int
intent: "Acotar un entero al rango cerrado [lo, hi]."
target: clamp.py
signature: "def clamp(x: int, lo: int, hi: int) -> int"
budget: { cyclomatic_max: 4, nesting_max: 2, params_max: 3, lines_max: 12 }
deps_allowed: []
forbids: ["import", "estado global"]
tests: test_clamp.py
test_command: "python -m unittest test_clamp.py"
require_test_approval: true
spec_version: "0.1"
tests_sha256: "57ef5e37f50d4725a3cf4bbc762cb973fe709cb5a8396e7b6a487f81c516eeac"
---

## Intent
Devolver `x` recortado al rango `[lo, hi]`. Asumir `lo <= hi`.

## Interface
```
in:  x: int, lo: int, hi: int  (lo <= hi)
out: int en [lo, hi]
error: no lanza
```

## Invariants
- `lo <= resultado <= hi` siempre.
- El resultado pertenece a {x, lo, hi}.
- Idempotente: `clamp(clamp(x)) == clamp(x)`.
- Si `lo <= x <= hi`, el resultado es `x` sin cambios.

## Examples
- `clamp(5, 0, 10)` → `5`
- `clamp(-3, 0, 10)` → `0`
- `clamp(20, 0, 10)` → `10`

## Do / Don't
- DO: comparar contra los extremos.
- DON'T: no importar nada; no usar estado global.

## Tests
Property-test congelado (`test_clamp.py`): enteros aleatorios + oráculo independiente
(`sorted([lo, x, hi])[1]`) + casos fijos. Existe antes de implementar.

## Constraints
- NO modificar nada fuera de `clamp`.
- NO añadir dependencias (`deps_allowed` vacío).
- PARAR y reportar si el budget no se cumple sin violar la interfaz. Sin workarounds silenciosos.
