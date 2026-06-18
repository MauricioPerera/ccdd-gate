---
task: treesitter-ts-backend
intent: "Backend de métricas TS/JS vía tree-sitter (backend universal, dep opcional)."
issue: MauricioPerera/ccdd-gate#1
target: runners/metrics_treesitter.py
tests: tests/test_treesitter_backend.py
spec_version: "0.1"
language: python
---

## Intent
El gate de complejidad medía solo Python (AST). Implementar el medidor para TS/JS con las MISMAS
métricas y el mismo shape, de modo que gate/task_gate/measure_complexity funcionen sobre `.ts/.js`.
Según la decisión #7, vía un **backend universal tree-sitter** (mapa de tipos de nodo por gramática),
no un runner Node a mano.

> Nota CCDD: unidad de módulo (backend + registro); disciplina vía gate de complejidad +
> tests congelados + la **suite de conformancia #8** como gate de aceptación.

## Interface
```
runners/metrics_treesitter.py
  LangSpec(language, extensions, grammar_loader, function_nodes, decision_nodes, nest_nodes,
           boolop_node, boolop_ops, params_field, name_field)   # mapa de nodos por gramática
  TreeSitterBackend(Backend): measure(src) -> [métricas crudas por función]  # mismo shape
  register_all() -> [lenguajes registrados]    # solo si tree_sitter + gramática están instalados

Lenguajes: typescript (.ts), tsx (.tsx), javascript (.js/.jsx/.mjs/.cjs)
Dep OPCIONAL: tree_sitter + tree_sitter_typescript. Sin ella -> solo Python (no rompe nada).
```

## Invariants
- Métricas estructurales (cyclomatic/nesting_depth/parameter_count) IDÉNTICAS al oráculo Python
  para la misma estructura lógica (pasa la suite de conformancia #8).
- `function_length` diverge por formato (llaves) -> override por-lenguaje en el manifest.
- ciclomática: +1 por if/for/while/do/ternario/catch y por cada rama de switch (case/default);
  +1 por cada `&&`/`||`. anidamiento: if/for/while/do/try (try anida pero no decide, como Python).
- Mismo `lint_results.schema.json`; `get_backend` enruta a TS cuando hay backend.
- Dep opcional: sin tree_sitter, todo sigue con Python. Determinista, sin LLM.

## Examples
- `function decode(rom, pc){ if(rom && pc){return 1;} return 2;}` -> cyclomatic 3, params 2.
- deep_nesting TS (for>if>while>try>if) -> nesting 5, cyclomatic 5 (igual que el fixture Python).

## Do / Don't
- DO: backend universal parametrizado por LangSpec; añadir lenguaje = añadir spec + gramática.
- DON'T: runner Node a mano por lenguaje; medir TS con el AST de Python.

## Tests
`tests/test_treesitter_backend.py` (skip si la dep no está): métricas/aridad/nombres TS, routing,
gate end-to-end sobre `.ts`, y que Python sigue disponible sin la dep. Conformancia: TS pasa #8.

## Constraints
- La dependencia va como **extra opcional** (requirements.txt comentado); no entra en el camino
  por defecto. PARAR y reportar si una gramática no reproduce una métrica sin divergencia
  justificable (se documenta en el manifest de conformancia, no se ocultan).
