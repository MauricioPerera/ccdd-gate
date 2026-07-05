---
type: 'Architecture'
title: 'Arquitectura general de ccdd-gate'
description: 'Los dos pilares (gate de código + evals), el servidor MCP y el flujo task-contract → lint → gate → veredicto, con los checks project-wide.'
tags: ['architecture', 'overview', 'mcp', 'gate']
---

# Arquitectura general de ccdd-gate

ccdd-gate es un árbitro determinista (sin LLM en el veredicto) que mantiene honesto al código escrito por IA. El formato de este nodo se define en [OKF-SPEC](../OKF-SPEC.md). El sustrato determinista se materializa en los principios de [Determinismo](../concepts/determinismo.md), y el contrato que gobierna una implementación se describe en [Task-contract](../concepts/task-contract.md).

## Los dos pilares

1. **Código** — gate de complejidad/tests: verifica que la función implementada respeta el budget firmado y pasa los property-tests congelados. 100% determinista.
2. **Comportamiento de agentes** — pilar de evals: para la salida NO determinista de un agente (texto/JSON), un dataset congelado + checks deterministas (schema, contención, citas/groundedness anti-alucinación, PII, trayectoria) deciden PASS/FAIL sin LLM (Tier 1); un juez LLM acotado y auditado contra un golden set es Tier 2 opt-in.

## El servidor MCP

- `runners/complexity_mcp.py` — servidor MCP (stdio JSON-RPC) que expone el sustrato como tools (sin LLM). Smoke test en `runners/mcp_smoke.py`. Es el punto de integración con el agente anfitrión (Claude Code, Cursor, etc.): el LLM grande planifica y audita; el sustrato decide el veredicto.

## Flujo task-contract → lint → gate → veredicto

```text
task-contract (.md) --(tc_lint)--> lint anti-desvarío
                  --(task_gate)--> tests congelados + complejidad ≤ budget + firma + deps opt-in
                                --> veredicto PASS/FAIL determinista
```

- `runners/tc_lint.py` — linter del task-contract (anti-desvarío del autor).
- `runners/task_gate.py` — veredicto unificado: `tc_lint` + tests congelados (sha256) + complejidad ≤ budget + gate-signature + deps opt-in + aprobación; `kind:group` compone hijas + test de integración.

El task-contract nativo de este repo se define en [Task-contract](../concepts/task-contract.md).

## Checks project-wide

Más allá del gate por función, el repo aplica checks sobre todo el código de producción:

- `runners/repo_gate.py` — dogfooding del complexity gate sobre el propio repo (sin LLM); FALLA si alguna función de producción entra en CRÍTICA.
- `runners/rules_gate.py` — checks deterministas project-wide por glob desde un `rules.yaml`.
- `runners/linter_gate.py` — envuelve linters externos deterministas (hoy `ruff`, pineado) como checks opt-in desde un `linters.yaml`.
- Auditorías: `runners/audit_composition.py` (composición sin gatear), `runners/audit_orphan_targets.py` (código huérfano), `runners/audit_annotations.py` (anotaciones sin importar), `runners/mutation_audit.py` (fuerza del oráculo vía mutation testing).

## Capa de métricas

La medición de complejidad es multi-lenguaje y vive detrás de una capa neutral registrada — ver [Backends de métricas](./metrics-backends.md).

## Límites de esta vista

No cubre la integración GitHub opcional (`integrations/github/`), el loop grande/pequeño (`runners/orchestrator.py`) ni el pilar de evals en detalle (Tier 1/2). Es la baseline; los detalles viven en nodos propios a medida se agreguen.