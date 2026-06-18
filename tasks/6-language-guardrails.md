---
task: language-guardrails
intent: "Guardrails language-aware: estructurales por backend y específicos por lenguaje."
issue: MauricioPerera/ccdd-gate#6
target: runners/complexity_mcp.py
tests: tests/test_language_guardrails.py
spec_version: "0.1"
language: python
---

## Intent
Los guardrails deterministas asumían Python. Separar: (a) texto-puro compartidos (secretos),
(b) estructurales (deep-nesting) calculados con el backend de métricas del lenguaje (no con el
regex de indentación, que asume Python), (c) específicos por lenguaje opt-in (p. ej. no-eval).

> Nota CCDD: unidad de módulo (scan_guardrails); disciplina vía gate de complejidad + tests.

## Interface
```
scan_guardrails(code, agent?, language?, filename?)   (MCP)
  language = language > extensión(filename) > python
  - texto-puro (no-secrets): regex compartido, dispara igual en cualquier lenguaje
  - estructural (deep-nesting): backend.measure(code), fira si nesting_depth >= RED.nesting (4);
    sin backend o código que no parsea -> degrada al regex del propio guardrail (no se pierde)
  - específicos del lenguaje (guardrails_lang.yaml): se añaden a los del contrato
  cada resultado lleva {id, fired, on_fail, method: regex|backend, language}

guardrails_lang.yaml   (nuevo, NO firmado): { <lenguaje>: [ {id, type, pattern, on_fail} ] }
```

## Invariants
- Secrets (on_fail abort) dispara y bloquea igual en python/typescript/go/…
- Sin `language`: python (back-compat); deep-nesting calculado con el backend python.
- Lenguaje sin backend: deep-nesting NO desaparece, cae al regex de indentación.
- Mismo `id` puede tener patrón distinto por lenguaje (no-eval: python eval/exec; JS new Function).
- Mismo formato de salida (on_fail) + campos añadidos (method/language), retrocompatible.
- Determinista, sin LLM.

## Examples
- `scan_guardrails(deep_python_code)` -> deep-nesting fired=true, method=backend.
- `scan_guardrails("new Function('x')", language="typescript")` -> no-eval fired=true.

## Do / Don't
- DO: estructurales por backend; texto-puro compartido; lang-specific opt-in y fuera del contrato.
- DON'T: medir anidamiento por indentación cuando hay backend; tocar el contrato firmado.

## Tests
`tests/test_language_guardrails.py` (congelados): secrets cross-lenguaje + bloqueo, deep-nesting
por backend (python) y fallback regex (go / código que no parsea), no-eval por lenguaje,
resolución por filename.

## Constraints
- Los guardrails específicos por lenguaje viven en `guardrails_lang.yaml` (opt-in); editar ese
  archivo NO requiere re-firmar el contrato.
- PARAR y reportar si un guardrail estructural necesita una métrica que el backend no provee.
