---
task: pluggable-metrics-backend
intent: "Backend de métricas pluggable por lenguaje con registro único get_backend."
issue: MauricioPerera/ccdd-gate#3
target: runners/metrics_backends.py
tests: tests/test_metrics_backends.py
spec_version: "0.1"
language: python
---

## Intent
Generalizar la extracción de métricas para que deje de estar clavada a Python: una capa neutral
compartida (umbrales firmados + `severity` + ensamblado de `lint_results`) y un registro por
lenguaje, manteniendo a Python como primer backend con **regresión cero**. Habilitador del epic #2.

> Nota CCDD: la unidad entregada es una **API de módulo** (registro + interfaz), no una función
> pura única, por lo que el `task_gate` por-firma no aplica tal cual. La disciplina se hace cumplir
> con (a) el **gate determinista de complejidad** sobre los archivos cambiados y (b) los **tests
> congelados** de `tests/test_metrics_backends.py` (valores oráculo + regresión).

## Interface
```
metrics_backends.get_backend(language=None, extension=None, filename=None) -> Backend
  precedencia: language > extension > extensión(filename) > DEFAULT_LANGUAGE ("python")
  KeyError si el lenguaje/extensión no tiene backend registrado (no no-op silencioso)

metrics_backends.Backend
  .language: str   .extensions: tuple   .tool: str   .version: str
  .measure(src) -> [ {function,line,cyclomatic,nesting_depth,parameter_count,function_length} ]
  .extract_source(src, filename) -> lint_results   (reusa el ensamblado compartido)

metrics_backends.register(backend)                 # idempotente, por language y extensions
metrics_backends.severity / AMBER / RED / build_findings   # ÚNICOS y compartidos

metrics.py  == primer backend (PythonBackend, AST stdlib); API pública intacta:
  functions_metrics(src), extract_source(src, name), extract(path), severity
```

## Invariants
- Python devuelve EXACTAMENTE los mismos números que antes (la suite existente pasa sin cambios).
- `severity` y los umbrales tienen una sola definición (compartida); ningún backend los duplica.
- Añadir un lenguaje = `register(backend)`; no se toca gate/runner/MCP.
- `lint_results.schema.json` no cambia; el shape de `lint_results` es idéntico entre lenguajes.
- Determinista, sin LLM.

## Tests
`tests/test_metrics_backends.py` (congelados): valores oráculo del backend Python (fixture anidado
y error de sintaxis), resolución de `get_backend` por las cuatro vías + `KeyError` en lenguaje no
registrado, y un backend ficticio que prueba que registrar = enchufar reusando la capa compartida.

## Constraints
- No cambiar `lint_results.schema.json` ni los umbrales firmados.
- Back-compat: sin `language`/`extension`, comportamiento Python idéntico al actual.
- Fuera de alcance (otras issues): dispatch por lenguaje en gate/runner/MCP (#5), `tc_lint` con
  `language` (#4), guardrails language-aware (#6), backend TS (#1), conformancia (#8).
