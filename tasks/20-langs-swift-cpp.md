---
task: langs-swift-cpp
intent: "Sumar Swift y C++ al backend tree-sitter con conformancia congelada."
issue: MauricioPerera/ccdd-gate#89
target: runners/metrics_treesitter.py
tests: tests/test_treesitter_backend.py
spec_version: "0.1"
language: python
---

## Intent
Segundo batch de lenguajes: los que la task 19 difirió por fragilidad. Viabilidad
verificada por el PM (RECON 2026-07-07, smoke real): `tree-sitter-swift` 0.7.3 y
`tree-sitter-cpp` 0.23.4 parsean sin errores `function_declaration` /
`function_definition`, métodos template de C++ (envueltos en `template_declaration`),
lambdas de C++ y closures de Swift. Mismo patrón que TAREA-RKC (task 19): `LangSpec`
declarativo + fixtures de conformancia con oráculo congelado + notas de modelado en el
manifest.

## Interface
```
runners/metrics_treesitter.py  2 LangSpec nuevos + loaders:
  swift (.swift)                — function_declaration; closures via anon_name_parents
  cpp   (.cpp, .cc, .cxx, .hpp) — function_definition; lambda_expression via
                                  anon_name_parents. La extensión .h QUEDA en C
                                  (conflicto decidido: .h ya enruta al backend c;
                                  documentarlo en el LangSpec de cpp).

fixtures/conformance/{swift,cpp}/  6 fixtures c/u (el set estándar menos `comprehension`)
  + entradas en manifest.json con `language_overrides` SOLO ante divergencia inevitable,
  cada una con su `note`. C++ suma un 7mo fixture propio `template_function` (función
  dentro de template_declaration → debe medirse igual que una función normal: el caso
  que motivó diferir C++).

.github/workflows/test.yml  el paso de gramáticas suma tree_sitter_swift tree_sitter_cpp.

tests/test_language_guardrails.py  SOLO la rotación ya conocida del ejemplar
  "sin backend": swift pasa a soportado, el ejemplar rota a lua (sin backend ni gramática
  instalada) — tercera rotación de la serie fb3977a (go→ruby) y task 19 (ruby→swift).
  Especificada acá a propósito: no es enmienda, es consecuencia conocida.
```

## Invariants
- Métricas estructurales (cyclomatic, nesting_depth, parameter_count) reproducen el
  oráculo congelado para la misma estructura lógica; `function_length` puede divergir
  por formato vía override declarado.
- Modelo de ramas de `switch` decidido y documentado en las notas del manifest:
  C++ `case_statement` incluye default (modelo TS/Java/C, ya fijado en el batch
  anterior); Swift `switch` con el modelo que la gramática permita, documentado con el
  porqué. Fixture `switch_case` → `cyclomatic=5` en ambos.
- `many_params` → `parameter_count=6`; `deep_nesting` → `nesting_depth=5` (documentar el
  análogo local del nido-sin-decisión: `defer`/`do` en Swift, bloque `{}` o `try` en C++).
- C++: una función DENTRO de `template_declaration` se encuentra y mide igual que una
  top-level (fixture `template_function` la congela); métodos calificados fuera de clase
  (`T C::get(...)`) se miden — si el nombre calificado no es un field plano, usar el hook
  `name_resolver` existente (introducido en task 19), y `sig_treesitter` degrada limpio
  (los tests de la task 18 NO se tocan).
- Sin gramática instalada: no-op anunciado. Capa neutral y thresholds intactos.
- Dogfooding verde: `repo_gate`, `linter_gate`, suite completa.

## Examples
- `many_params` en swift/cpp -> `parameter_count=6`.
- `deep_nesting` en ambos -> `nesting_depth=5`.
- `switch_case` en ambos -> `cyclomatic=5` con el modelo documentado.
- `template_function` (solo cpp) -> misma métrica que su gemela sin template.
- `supported_languages()` post-task incluye `swift` y `cpp`.

## Do / Don't
- DO: reporte de decisiones de modelado por lenguaje en `.agents/logs/T20-REPORT.md`
  (espejo de TAREA-RKC), con las notas durables en el manifest.
- DO: fixtures que parseen de verdad (`has_error=False` verificado en test).
- DON'T: copiar overrides sin justificar; tocar thresholds ni la capa neutral; registrar
  un lenguaje cuyos fixtures no reproduzcan el oráculo.
- DON'T: darle `.h` a cpp (queda en C; documentado).

## Tests
Extender `tests/test_treesitter_backend.py` vía `manifest.json` (mismo mecanismo
data-driven, sin ifs por lenguaje); unitarios de anónimas (closure Swift asignada,
lambda C++ en auto) y de `template_function`; skip limpio y anunciado sin gramática;
rotación del ejemplar en `test_language_guardrails.py` con el comentario actualizado
(tercera rotación, citar la serie).

## Constraints
- PARAR y reportar si... una gramática no distingue un concepto que el oráculo exige
  (documentar y proponer el modelo con evidencia antes de congelar valores); o si los
  métodos template/calificados de C++ no pudieran medirse sin refactor de la capa
  neutral — en ese caso documentar la clase excluida con su fixture demostrativo y
  cerrar el batch con lo medible declarado, en vez de aproximar en silencio.
