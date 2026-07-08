---
task: signature-treesitter
intent: "Validar la firma de contratos no-Python con parsing real vía tree-sitter, no aridad genérica."
issue: MauricioPerera/ccdd-gate#84
target: runners/sig_treesitter.py
tests: tests/test_sig_treesitter.py
spec_version: "0.1"
language: python
---

## Intent
Hoy la firma de un contrato no-Python se valida por **aridad genérica** (`tc_lint.parse_sig`
→ `_parse_sig_generic`, warning `tc-signature-generic`), y `check_signature`/`sig_check.py`
son Python-only (`ast`). Es el check determinista más débil del multi-lenguaje: cuenta
parámetros pero no compara nombres, y una firma implementada con nombres distintos pasa.
Las gramáticas tree-sitter YA están instaladas y mapeadas (`SPECS` de
`metrics_treesitter.py`, con `params_field` por lenguaje): extraer nombre + nombres de
parámetros reales es el mismo movimiento que el hook `_go_param_count` hizo para la
aridad, aplicado a la firma completa.

## Interface
```
runners/sig_treesitter.py  (nuevo, dep opcional — patrón de metrics_treesitter)
  parse_signature(signature, language) -> {"name": str, "params": [str, ...]} | None
      None si la gramática del lenguaje no está instalada o el snippet no parsea como
      declaración de función. `params` en orden, solo nombres (sin tipos ni defaults).
  check_signature_src(source, fn_name, expected_signature, language, target_line=None) -> str
      "" si la firma implementada coincide (nombre + nombres de params en orden);
      cadena no vacía con el desajuste en caso contrario. Espejo de sig_check para Python.

runners/tc_lint.py  parse_sig(signature, language) usa sig_treesitter cuando el lenguaje
  tiene LangSpec y su gramática está instalada; degrada al camino actual (aridad genérica
  + warning tc-signature-generic) cuando no — degradación ANUNCIADA, nunca silenciosa.

MCP check_signature  gana parámetro opcional `language` (default python, back-compat).
```

## Invariants
- El camino Python queda INTACTO: mismo AST nativo, mismos veredictos byte a byte.
- Sin `tree_sitter` o sin la gramática del lenguaje: comportamiento idéntico al actual
  (aridad genérica + warning). El default zero-dep del repo no cambia.
- La comparación es por nombre de función + nombres de parámetros en orden; tipos,
  defaults y anotaciones se ignoran (espejo del `sig_check` Python).
- Se REUTILIZAN los `SPECS`/loaders de `metrics_treesitter.py` (params_field,
  params_counter, name_field): un solo mapa por lenguaje, sin duplicarlo.
- Go agrupado `func f(a, b int)` extrae `["a", "b"]` (la clase de bug que `_go_param_count`
  cerró para la aridad no puede reaparecer en la firma).
- Determinista, sin LLM, sin red; lenguajes cubiertos = los de `SPECS` (ts/tsx/js/rust/
  go/java/csharp/php) — la lista sale de `supported_languages()`, no se hardcodea aparte.

## Examples
- Contrato TS `"function verify(id: string): boolean"` + impl `function verify(id) {...}` -> `""`.
- Misma firma + impl `function verify(userId) {...}` -> mismatch que nombra `id` vs `userId`.
- Go `"func f(a, b int)"` -> `{"name": "f", "params": ["a", "b"]}`.
- `language: kotlin` (sin LangSpec hoy) -> `parse_signature` devuelve None y `tc_lint`
  emite `tc-signature-generic`, como hoy.
- Dos funciones homónimas en el source + `target_line` -> verifica la de esa línea.

## Do / Don't
- DO: fixtures de firma por lenguaje reutilizando los fuentes de `fixtures/conformance/`
  donde alcancen (ya tienen funciones con params conocidos).
- DO: mensajes de mismatch con esperado vs encontrado, en ASCII.
- DON'T: romper la firma del MCP `check_signature` sin `language` (back-compat Python).
- DON'T: duplicar los mapas de nodos por lenguaje fuera de `SPECS`.
- DON'T: exigir tree-sitter en el camino por defecto (sigue siendo dep opcional).

## Tests
`tests/test_sig_treesitter.py`: por cada lenguaje con gramática instalada — extracción de
nombre+params desde una declaración representativa (incluido el caso Go agrupado);
mismatch por nombre de param, por cantidad y por nombre de función; homónimos con
`target_line`; fallback limpio sin gramática (monkeypatch del import); camino Python
inalterado (mismos veredictos que `sig_check`); integración `tc_lint.parse_sig` con y sin
gramática (warning presente solo en el fallback).

## Constraints
- PARAR y reportar si... alguna gramática no expone los nombres de parámetros de forma
  estable para su LangSpec (documentar el hallazgo y excluir ESE lenguaje del parsing
  preciso manteniendo su fallback, en vez de aproximar), o si el cambio exigiera tocar
  los thresholds firmados o el shape de `lint_results`.
