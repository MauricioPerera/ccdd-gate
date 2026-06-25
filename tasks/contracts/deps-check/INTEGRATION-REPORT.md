# DEPS-GATE-INTEGRATION-REPORT

Cableado de la etapa **OPT-IN** `gate-deps` (enforcement de `deps_allowed`) en el gate de función + tool MCP `scan_dependencies`. Determinista, sin LLM en el gate.

## Qué toqué

### 1. `runners/task_gate.py`
- Importé `deps_check` junto al resto de los módulos del runner.
- Añadí `_gate_deps(fm, target)`:
  - Si NO `fm.get("enforce_deps")` → devuelve `None` (opt-in, no corre; back-compat).
  - Si el target no existe → devuelve `None` (lo reporta `_gate_complexity` como hoy).
  - Si no → calcula `deps_check.unauthorized_imports(source, fm.get("deps_allowed") or [])`. Lista no vacía → `{"verdict":"FAIL","stage":"gate-deps","unauthorized": <lista>}`. Vacía → `None`.
- Cableé `_gate_deps(fm, target)` en `gate()` de los contratos de FUNCIÓN, en la cadena de `or`, **después** de `_gate_run_tests`/`_gate_annotations` y **antes** de `_gate_complexity`.

### 2. `runners/complexity_mcp.py`
- Añadí la tool MCP `scan_dependencies` (inputSchema: `code` string requerido, `deps_allowed` array opcional) a la lista `TOOLS`.
- Añadí la función `scan_dependencies(args)` → `{"unauthorized": deps_check.unauthorized_imports(args["code"], args.get("deps_allowed") or [])}`.
- La registré en el dict `DISPATCH`.

### 3. `task_contract.schema.json` (opcional)
- Añadí `enforce_deps` (boolean) a `properties`.

## NO toqué
- `tests/test_deps_gate.py`, `tests/test_deps_check.py` ni `runners/deps_check.py` (tests/núcleo congelados).

## Criterio de verde

```
python -m unittest discover -s tests -p "test_*.py"
```
→ **Ran 225 tests in 6.723s — OK** (verde; incluye los 3 tests de `DepsGate` y los 11 de `TestUnauthorizedImports`).

```
python runners/mcp_smoke.py
```
→ **OK** — el servidor responde el protocolo y las 4 tools del smoke funcionan; `tools/list` ahora incluye `scan_dependencies`. Verificación ad-hoc de la tool: `scan_dependencies({code:"import os\nimport requests\nfrom flask import Flask", deps_allowed:["requests"]})` → `{"unauthorized":["flask"]}`.