---
task: conformance-suite
intent: "Suite de conformancia de métricas cross-lenguaje con oráculo congelado."
issue: MauricioPerera/ccdd-gate#8
target: tests/test_conformance.py
tests: tests/test_conformance.py
spec_version: "0.1"
language: python
---

## Intent
Garantizar que todos los backends de métricas COINCIDEN en la definición de cada métrica. Sin un
oráculo común, cada backend mediría a su manera y el veredicto dejaría de ser comparable entre
lenguajes. Python define el baseline; todo backend nuevo debe reproducir el oráculo.

> Nota CCDD: unidad de datos+test (fixtures + oráculo); disciplina vía la propia suite + gate.

## Interface
```
fixtures/conformance/manifest.json
  fixtures[]: {id, target, expected{4 métricas}, language_overrides{lang:{...}},
               cross_language_divergence_allowed[], sources{lang: path}, note}
fixtures/conformance/<lang>/<fixture>.<ext>   (misma estructura lógica por lenguaje)
tests/test_conformance.py
  parametrizado por (lenguaje registrado, fixture con fuente) -> assert métricas == oráculo
```

## Invariants
- Fixtures: simple, deep_nesting (5), many_params (6), long_function (>80), boolop_chain,
  comprehension, switch_case.
- Estructurales (cyclomatic/nesting_depth/parameter_count) coinciden entre lenguajes.
- function_length se compara por-lenguaje (formato) vía language_overrides.
- Divergencias inevitables: declaradas en cross_language_divergence_allowed + override + note.
- Python pasa la suite con sus valores actuales (baseline). Determinista, sin LLM.

## Examples
- `boolop_chain`: cyclomatic=4 (1 + (4 operandos − 1)).
- `switch_case`: cyclomatic=5 (1 + 4 ramas); nesting_depth=0 en Python (divergencia documentada).

## Do / Don't
- DO: oráculo independiente y congelado; un backend nuevo se valida contra él.
- DON'T: ajustar el oráculo para que “pase” un backend; las divergencias se documentan, no se ocultan.

## Tests
`tests/test_conformance.py` (congelados): manifest bien formado, baseline Python completo, y match
del oráculo para todo backend registrado con fuente (hoy: Python; TS entra con #1).

## Constraints
- Reusa `lint_results.schema.json` como contrato de forma. Sin LLM.
- PARAR y reportar si un backend no puede reproducir una métrica sin una divergencia justificable.
