---
task: popcount
intent: "Contar los bits en 1 de un entero no negativo."
target: popcount.py
signature: "def popcount(n: int) -> int"
budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 1, lines_max: 12 }
deps_allowed: []
forbids: ["import", "bin("]
tests: test_popcount.py
require_test_approval: true
spec_version: "0.1"
tests_sha256: "697191cd53a22f8b577f7e495f188b1eb779fb2648be2711747701211bb1cbd1"
---

## Intent
Devolver cuántos bits valen 1 en la representación binaria de `n` (n >= 0).

## Interface
```
in:  n: int  (n >= 0)
out: int >= 0  (cantidad de bits en 1)
error: no lanza para n >= 0
```

## Invariants
- Resultado >= 0 siempre.
- Resultado <= número de bits de `n` (`n.bit_length()`).
- `popcount(0) == 0`.
- `popcount(2**k) == 1` para todo k >= 0.

## Examples
- `popcount(0)` → `0`
- `popcount(7)` → `3`
- `popcount(255)` → `8`

## Do / Don't
- DO: recorrer/desplazar bits con operaciones enteras.
- DON'T: no usar `bin()`; no importar nada.

## Tests
Property-test congelado (`test_popcount.py`): enteros no negativos aleatorios + oráculo
independiente (`bin(n).count("1")`) + casos fijos. Existe antes de implementar.

## Constraints
- NO modificar nada fuera de `popcount`.
- NO usar `bin()` ni dependencias.
- PARAR y reportar si el budget no se cumple sin violar la interfaz. Sin workarounds silenciosos.
