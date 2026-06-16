---
task: chunk-list
intent: "Partir una lista en sublistas consecutivas de tamaño fijo."
target: chunk.py
signature: "def chunk(items: list, size: int) -> list"
budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 2, lines_max: 14 }
deps_allowed: []
forbids: ["import", "estado global"]
tests: test_chunk.py
require_test_approval: true
spec_version: "0.1"
tests_sha256: "b54d89e6f8e9b4438d25cff657a85b3ce414a7d1d2527bda7f96519a62258154"
---

## Intent
Devolver una lista de sublistas consecutivas de `items`, cada una de longitud `size`
(la última puede ser más corta).

## Interface
```
in:  items: list, size: int  (size >= 1)
out: list[list]  (sublistas consecutivas)
error: si size < 1 lanza ValueError
```

## Invariants
- Concatenar las sublistas reconstruye `items` en orden (sin pérdidas ni reordenamientos).
- Todas las sublistas tienen longitud `size` salvo, a lo sumo, la última (1..size).
- `items == []` → `[]`.
- `size < 1` → ValueError (no devuelve una lista).

## Examples
- `chunk([1,2,3,4], 2)` → `[[1,2],[3,4]]`
- `chunk([1,2,3], 2)` → `[[1,2],[3]]`
- `chunk([], 3)` → `[]`

## Do / Don't
- DO: cortar por rebanadas consecutivas.
- DON'T: no importar nada; no descartar el resto que no completa una sublista.

## Tests
Property-test congelado (`test_chunk.py`): listas y tamaños aleatorios + oráculo independiente
(reconstrucción por concatenación y chequeo de longitudes) + caso `size < 1` que lanza
ValueError + casos fijos. Existe antes de implementar.

## Constraints
- NO modificar nada fuera de `chunk`.
- NO añadir dependencias.
- PARAR y reportar si el budget no se cumple sin violar la interfaz. Sin workarounds silenciosos.
