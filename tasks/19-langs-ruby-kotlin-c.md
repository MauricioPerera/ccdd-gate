---
task: langs-ruby-kotlin-c
intent: "Sumar Ruby, Kotlin y C al backend tree-sitter con conformancia congelada."
issue: MauricioPerera/ccdd-gate#85
target: runners/metrics_treesitter.py
tests: tests/test_treesitter_backend.py
spec_version: "0.1"
language: python
---

## Intent
Añadir un lenguaje al gate = `LangSpec` declarativo + fixtures de conformancia que
reproduzcan el oráculo congelado (patrón #7/#8, demostrado con el batch Java/C#/PHP en
TAREA-JCSPHP). Este task suma **Ruby, Kotlin y C** — elegidos por madurez de gramática,
verificada en PyPI (RECON 2026-07-07): `tree-sitter-ruby` 0.23.1 (oficial),
`tree-sitter-kotlin` 1.1.0, `tree-sitter-c` 0.24.2 (oficial). Swift y C++ quedan
deliberadamente para el siguiente batch (gramáticas más frágiles/complejas: build pesado
de swift, templates/métodos fuera de clase en C++).

## Interface
```
runners/metrics_treesitter.py  3 LangSpec nuevos + loaders:
  ruby   (.rb)          — method / singleton_method / lambda / block como corresponda
  kotlin (.kt, .kts)    — function_declaration / lambdas
  c      (.c, .h)       — function_definition (C no tiene anónimas: sin anon_name_parents)

fixtures/conformance/{ruby,kotlin,c}/  6 fixtures c/u (todos menos `comprehension`,
  que es sintaxis solo-Python) + entradas en manifest.json con `language_overrides`
  SOLO donde haya divergencia inevitable (function_length/nesting) y su razón en `note`.

.github/workflows/test.yml  el paso opcional de gramáticas suma las 3 nuevas.
```

## Invariants
- Las métricas ESTRUCTURALES (cyclomatic, nesting_depth, parameter_count) reproducen el
  oráculo congelado del manifest para la misma estructura lógica; `function_length` puede
  divergir por formato (llaves/`end`) vía override declarado.
- El modelo de ramas de `case/when` (Ruby), `when` (Kotlin) y `switch` (C) se DECIDE y
  DOCUMENTA explícitamente (¿cada rama suma?, ¿default/else suma?) en un reporte
  TAREA-RKC, espejo de TAREA-JCSPHP — la decisión queda fijada por los fixtures
  `switch_case`, que deben dar `cyclomatic=5`.
- Parámetros agrupados estilo Go: VERIFICAR por gramática si existe el caso (no asumir);
  si una gramática agrupa nombres en un nodo, va hook `params_counter` con fixture de
  regresión en `many_params` (que debe dar `parameter_count=6` en los 3).
- Anónimas nombradas vía `anon_name_parents` donde el lenguaje las tenga (lambda/proc en
  Ruby, lambdas en Kotlin); C queda sin reglas de anónimas (no las tiene).
- Sin la gramática instalada: no-op anunciado, nada se rompe (patrón de dep opcional).
- El dogfooding del repo (`repo_gate`, linter_gate, suite) sigue verde; la capa neutral
  (`metrics_backends`, thresholds firmados) NO se toca.

## Examples
- `many_params` en ruby/kotlin/c -> `parameter_count=6`.
- `deep_nesting` en los 3 -> `nesting_depth=5` (elegir y documentar el análogo local del
  nido-sin-decisión: `begin/ensure` Ruby, `try/finally` Kotlin, bloque `{}` o análogo en C).
- `switch_case` en los 3 -> `cyclomatic=5` con el modelo de ramas documentado.
- `supported_languages()` post-task incluye `ruby`, `kotlin`, `c` cuando sus gramáticas
  están instaladas.

## Do / Don't
- DO: reporte TAREA-RKC con cada decisión de modelado y su porqué (es el entregable que
  hace auditable el oráculo).
- DO: fixtures que parseen de verdad con su gramática (verificado en test, no a ojo).
- DON'T: copiar `language_overrides` de otro lenguaje sin justificar la divergencia.
- DON'T: tocar thresholds, severity ni el shape de `lint_results`.
- DON'T: registrar un lenguaje cuyos fixtures no reproduzcan el oráculo (mejor no
  soportarlo que soportarlo mal — la conformancia ES la definición de soportado).

## Tests
Extender `tests/test_treesitter_backend.py`: la suite de conformancia recorre los 3
lenguajes nuevos vía `manifest.json` (mismo mecanismo que los 7 actuales, sin ifs por
lenguaje); casos unitarios de anónimas (Ruby lambda asignada, Kotlin lambda en val) y del
hook de params si algún lenguaje lo necesita; skip limpio y anunciado si la gramática no
está instalada.

## Constraints
- PARAR y reportar si... una gramática no distingue un concepto que el oráculo exige
  (p. ej. ramas de `when` de Kotlin sin nodo propio por rama): documentar el hallazgo y
  proponer el modelo con evidencia ANTES de congelar valores en el manifest, en vez de
  forzar un override sin razón; o si `tree-sitter-kotlin` (community) resultara
  incompatible con la versión pineada de `tree_sitter` — en ese caso el batch se cierra
  con ruby+c y kotlin queda documentado como bloqueado.
