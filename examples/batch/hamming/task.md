---
task: hamming-distance
intent: "Contar las posiciones en que dos cadenas de bytes difieren."
target: hamming.py
signature: "def hamming_distance(a: bytes, b: bytes) -> int"
budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 2, lines_max: 12 }
deps_allowed: []
forbids: ["import", "estado global"]
tests: test_hamming.py
test_command: "python -m unittest test_hamming.py"
require_test_approval: true
spec_version: "0.1"
tests_sha256: "84497fb903df34bc09eadfcfe685e791ce681c191142ea46f2eb486c145bf64d"
---

## Intent
Devolver cuántas posiciones difieren entre `a` y `b`, ambas de igual longitud.

## Interface
```
in:  a: bytes, b: bytes  (len(a) == len(b))
out: int >= 0  (posiciones distintas)
error: si len(a) != len(b) lanza ValueError
```

## Invariants
- Resultado en `[0, len(a)]`.
- `hamming_distance(a, a) == 0` (reflexividad).
- Simétrico: `hamming_distance(a, b) == hamming_distance(b, a)`.
- Longitudes distintas → ValueError (no devuelve un número).

## Examples
- `hamming_distance(b"abc", b"abc")` → `0`
- `hamming_distance(b"abc", b"abd")` → `1`
- `hamming_distance(b"\x00\x00", b"\xff\xff")` → `2`

## Do / Don't
- DO: comparar byte a byte sobre la longitud común.
- DON'T: no importar nada; no truncar silenciosamente cadenas de distinta longitud.

## Tests
Property-test congelado (`test_hamming.py`): pares de bytes aleatorios de igual longitud +
oráculo independiente (`sum(x != y for x, y in zip(a, b))`) + caso de longitudes distintas
que debe lanzar ValueError + casos fijos. Existe antes de implementar.

## Constraints
- NO modificar nada fuera de `hamming_distance`.
- NO añadir dependencias.
- PARAR y reportar si el budget no se cumple sin violar la interfaz. Sin workarounds silenciosos.
