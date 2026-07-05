# Reglas para Agentes de IA

Si eres un agente de IA interactuando con este repositorio, debes acatar las siguientes reglas:

1. **Metodología KDD Obligatoria**: Este repositorio utiliza Knowledge-Driven Development. Antes de escribir código, debes leer los contratos en `knowledge/contracts/` y la spec normativa de los nodos OKF en `knowledge/OKF-SPEC.md`.
2. **Carga la Skill Local**: Tienes disponible la skill `kdd-okf-ccdd-hybrid` en el directorio `.agents/skills/`. Debes adoptarla en tu contexto para entender cómo generar y validar los contratos híbridos OKF-CCDD.
3. **No dupliques contexto**: Utiliza enlaces de markdown relativos a `knowledge/` cuando necesites explicar el porqué de una implementación.
4. **Validación Determinista (dos niveles)**:
   - **Nivel 1 (incluido, obligatorio):** `python scripts/validate_contracts.py knowledge/contracts` + el `test_command` del contrato. Ambos corren local y en CI.
   - **Nivel 2 (NATIVO en este repo):** el gate CCDD real vive en este propio repositorio, no es un MCP externo. Se invoca con `python runners/tc_lint.py <contrato>` (lint del contrato) y `python runners/task_gate.py <contrato>` (veredicto: tests congelados + complejidad ≤ budget + firma). Ningún contrato se considera terminado hasta que pase el nivel 1.
5. **Precedencia del Budget**: en este repo el gate CCDD está **siempre** disponible (es nativo), así que la config firmada del gate (`contracts/complexity-agent`) **manda siempre** — el `budget` del frontmatter solo puede ser ≤ a los topes firmados y ante conflicto gana la config firmada. El validador incluido (nivel 1) solo verifica la **presencia** del `budget`; los topes los enforce el gate nativo (nivel 2).
6. **Ciclo de Vida del Contrato**: `draft` -> `validated` (validador + `tc_lint` en verde) -> `implemented` (`test_command` en verde) -> `verified` (salida REAL de los comandos pegada en `.agents/logs/<task>-REPORT.md`; ese directorio está gitignorado a propósito).

## Verificaciones del repo que DEBEN quedar verdes

- `python scripts/validate_contracts.py knowledge/contracts` — validador de contratos KDD (nivel 1).
- `python -m unittest discover -s tests -p "test_*.py"` — suite completa (no uses `pytest` a secas).
- `python runners/repo_gate.py PASS` — dogfooding del complexity gate sobre código de producción.
- `python runners/linter_gate.py linters.yaml .` — linters externos pineados (ruff; exit 0).
- `python runners/mcp_smoke.py` — smoke test del servidor MCP.