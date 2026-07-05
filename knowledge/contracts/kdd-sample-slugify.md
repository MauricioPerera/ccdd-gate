---
type: 'Task Contract'
title: 'Slugify de ejemplo (KDD híbrido)'
description: 'Función pura que convierte texto arbitrario en un slug ASCII seguro para URLs.'
tags: ['ccdd', 'kdd', 'example']

task: kdd-sample-slugify
intent: "Convertir un texto arbitrario en un slug ASCII seguro para URLs."
target: ../../src/kdd_sample/slugify.py
signature: "def slugify(text: str) -> str"
test_command: "python -m unittest tests.test_kdd_sample"
test_cwd: ../..
budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 1, lines_max: 20 }
tests: ../../tests/test_kdd_sample.py
deps_allowed: []
forbids: ['network', 'subprocess']
---

## Intent
Función pura que normaliza un `str` arbitrario a un **slug**: solo ASCII alfanumérico en
minúsculas, palabras separadas por un único `-`, sin `-` en los extremos. Es el perro de
verano del gate: un contrato chico y autocontenido que ejercita el ciclo de vida KDD
(composición `OKF → CCDD → gate`) de punta a punta. El veredicto es determinista
([determinismo](../concepts/determinismo.md)): mismo input, mismo slug, corrida a corrida.

## Interface
```
in:  text: str            (cualquier string, incluido vacío o solo símbolos)
out: str                  (slug ASCII en minúsculas; "" si no queda ningún alnum)
error: no lanza           (entrada vacía / solo símbolos -> "")
pureza: sí                (no I/O, no estado, stdlib únicamente)
```

## Invariants
- El resultado solo contiene `[a-z0-9]` y `-`; nunca otro carácter.
- Nunca hay dos `-` adyacentes; nunca `-` al inicio o al final.
- `slugify("")` == `""`; `slugify("!!!")` == `""`.
- Función pura: no lee/escribe estado, no llama a la red ni a subprocesos
  (ver [task-contract](../concepts/task-contract.md)).

## Examples
- `slugify("Hello World!")` → `"hello-world"`
- `slugify("Foo--Bar  Baz")` → `"foo-bar-baz"`
- `slugify("  Hola   Mundo  ")` → `"hola-mundo"`

## Do / Don't
- DO: una sola pasada sobre `text.lower()`, colapsando corridas de separadores.
- DO: stdlib únicamente (`deps_allowed: []`).
- DON'T: no `import` de tercero, no `print`, no `open`, no `subprocess`.
- DON'T: no usar regex (`re`); queda fuera del espíritu "chiquita y pura".

## Tests
Property-tests congelados en [`../../tests/test_kdd_sample.py`](../../tests/test_kdd_sample.py):
cubren los Examples del contrato más los bordes (vacío, solo símbolos, unicode básico donde
los no-ASCII colapsan a `-`). El oráculo es independiente de la implementación: asserts
sobre la forma del slug, no sobre el algoritmo. Se ejecutan con
`python -m unittest tests.test_kdd_sample`.

## Constraints
- Solo ASCII `[a-z0-9-]` en la salida; cualquier carácter fuera de ese set (incluido
  unicode no-ASCII como `é` o `ñ`) colapsa a `-`.
- `budget` ≤ topes firmados del gate (`cyclomatic_max: 5`, `nesting_max: 2`); ver
  [determinismo](../concepts/determinismo.md).
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz o la pureza.
  Sin workarounds silenciosos: si la función no cabe holgada en el budget, devolverla para
  más descomposición en vez de inflar el tope.