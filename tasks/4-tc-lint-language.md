---
task: tc-lint-language
intent: "Campo language en el front-matter y validación de signature por lenguaje."
issue: MauricioPerera/ccdd-gate#4
target: runners/tc_lint.py
tests: tests/test_tc_lint_language.py
spec_version: "0.1"
language: python
---

## Intent
`tc_lint.parse_sig` validaba la `signature` como `def` de Python; un contrato para TS/Go fallaba
`tc-signature-valid` aunque fuera correcto. Añadir un campo `language` (default `python`) y
despachar la validación de firma por lenguaje, sin romper contratos sin el campo.

> Nota CCDD: unidad de módulo (reglas de lint), no función pura única; disciplina vía gate de
> complejidad + tests congelados (`tests/test_tc_lint_language.py`).

## Interface
```
front-matter: language?: str   (default "python"; enum abierto: python|typescript|javascript|go|…)

tc_lint.parse_sig(signature, language=None) -> (name, arity)
  python              -> AST nativo (preciso, valida sintaxis de def)
  resto               -> aridad genérica (nombre + nº params top-level), sin deps

reglas nuevas:
  tc-language          error si language no es string no vacío
  tc-signature-generic warn  cuando se valida por aridad genérica (sin parser nativo)
```

## Invariants
- Sin `language` (o `python`): comportamiento idéntico al actual (sin warning genérico).
- `language: typescript` + firma TS válida: pasa `tc-signature-valid` y respeta `params_max`.
- Aridad genérica respeta `()[]{}<>` y comillas (genéricos/tuplas/defaults no inflan el conteo).
- Las demás reglas (`tc-required`, `tc-intent-atomic`, `tc-budget-sane`, `tc-tests-frozen`,
  `tc-sections`, `tc-stop-rule`) quedan intactas.
- `lint_task_contract` (MCP) propaga `language` (viene en el front-matter del contrato).
- Determinista, sin LLM.

## Examples
- `parse_sig("function decode(rom: Uint8Array, pc: number): R", "typescript")` -> `("decode", 2)`
- `parse_sig("func Decode(rom []byte, pc int) (string, int)", "go")` -> `("Decode", 2)`

## Do / Don't
- DO: degradar con warning explícito cuando no hay parser nativo.
- DON'T: añadir dependencias (parser TS real) — fuera de alcance; queda para #1.

## Tests
`tests/test_tc_lint_language.py` (congelados): aridad+nombre cross-lenguaje, params_max en TS,
firma no parseable, language inválido, y back-compat python (sin warning genérico).

## Constraints
- No tocar los rubrics FIRMADOS (`contracts/task-author-agent/*`): documentar `language` ahí
  exigiría re-firmar (`lint --sign`) + atestación Ed25519 (gobernanza L2). Se documenta en el
  README; la actualización del rubric firmado queda como paso de gobernanza aparte.
- PARAR y reportar si un lenguaje necesita parser nativo real (no forzar): eso es #1 (backend TS).
