---
task: language-dispatch
intent: "Dispatch por lenguaje en gate/runner y measure_complexity(language)."
issue: MauricioPerera/ccdd-gate#5
target: runners/complexity_gate.py
tests: tests/test_language_dispatch.py
spec_version: "0.1"
language: python
---

## Intent
Los puntos de entrada asumían Python (`complexity_gate` ignoraba todo lo no-`.py` en silencio;
`measure_complexity` medía siempre Python). Enrutar por backend de lenguaje (extensión o flag),
con no-op/abort **explícito** cuando no hay backend. Default Python (back-compat).

> Nota CCDD: unidad de wiring multi-módulo; disciplina vía gate de complejidad + tests congelados.

## Interface
```
complexity_gate.py archivo [--language LANG]
  backend por --language o extensión; sin backend -> aviso por stderr + exit 0 (no-op, no silencio)
  con backend -> mide; CRÍTICA -> exit 2

complexity_runner.py --input archivo [--language LANG]
  backend por --language o extensión; sin backend -> fail(3) explícito

measure_complexity(code, filename?, language?)   (MCP)
  language > extensión(filename) > python; sin backend -> {error, available_languages}
```

## Invariants
- `.py` se mide exactamente igual que antes (mismos números, mismos exits).
- Extensión sin backend en el hook/CLI: no-op ANUNCIADO (exit 0), nunca silencioso.
- `measure_complexity` sin `language` ni extensión conocida: python (back-compat).
- No cambia el contrato JSON-RPC (solo añade el parámetro opcional `language`).
- Determinista, sin LLM.

## Examples
- `complexity_gate.py x.ts` (sin backend TS) -> stderr "sin backend…", exit 0.
- `measure_complexity({code, language:"python"})` -> tool "ccdd-ast-metrics".

## Do / Don't
- DO: precedencia language > extensión > default; aviso explícito ante ausencia de backend.
- DON'T: medir un lenguaje con el AST de Python (falsos números); preferir no-op anunciado.

## Tests
`tests/test_language_dispatch.py` (congelados): CLI del gate (py CRÍTICA/clean, .ts no-op,
--language fuerza backend), `measure_complexity` (default/filename/language/backend ficticio/
desconocido), y `complexity_runner.build_inputs` (python OK, sin backend -> SystemExit 3).

## Constraints
- `scan_guardrails` language-aware queda en #6 (esta issue no lo toca).
- PARAR y reportar si una extensión no tiene backend (no medir con un backend ajeno).
