---
type: 'Concept'
title: 'Task-contract'
description: 'El contrato CCDD nativo de este repo: frontmatter, 7 secciones, tests congelados con sha256 y budget firmado.'
tags: ['concept', 'task-contract', 'ccdd', 'contract']
---

# Task-contract (contrato CCDD nativo)

Un task-contract es la unidad atómica de trabajo que un agente efímero implementa bajo el gate. Es **front-matter YAML** (machine-checkable) + **cuerpo Markdown** (prescriptivo). Regla central: **especifica el contrato y los property-tests con oráculo independiente, NO el algoritmo**. El formato de este nodo se define en [OKF-SPEC](../OKF-SPEC.md); encaja en la [Arquitectura general](../architecture/overview.md) y se rige por el [Determinismo](./determinismo.md).

## Forma (frontmatter)

La forma del front-matter está fijada por [`task_contract.schema.json`](../../task_contract.schema.json) (jsonschema). `tc_lint` valida la FORMA contra ese schema (capa 1) y aplica sus reglas semánticas aparte (capa 2). Campos clave: `task`, `intent`, `target`, `signature`, `budget`, `tests`, `test_command`; más campos opt-in de gates de antipatrones (`pure`, `forbid_assert`, `forbid_bare_except`, etc.) y `kind:group` para componer hijas.

## Las 7 secciones del cuerpo

El cuerpo es prescriptivo y tiene siete secciones obligatorias — las mismas que valida el KDD validator (`scripts/validate_contracts.py`) sobre los contratos híbridos de `knowledge/contracts/`:

1. `## Intent` — qué hace, atómico.
2. `## Interface` — la firma que el implementador debe respetar.
3. `## Invariants` — propiedades que siempre valen.
4. `## Examples` — casos concretos (≥2).
5. `## Do / Don't` — guía de estilo.
6. `## Tests` — dónde viven los property-tests congelados.
7. `## Constraints` — debe contener la frase `PARAR y reportar si`.

## Tests congelados con sha256

Los property-tests se **congelan y firman antes** de que el implementador toque la tarea: `tests_sha256` (firmado por `runners/approve_tests.py`) es un gate de aprobación byte-exacto. El implementador no puede ablandar el oráculo. La fuerza de ese oráculo se mide con `runners/mutation_audit.py` (un mutante sobreviviente delata un test débil).

## Budget firmado

El `budget` del contrato (topes de complejidad) **solo puede ser ≤** los topes firmados en la config del gate (`contracts/complexity-agent`). Ante cualquier conflicto gana la config firmada del gate — ver precedencia de budget en [Determinismo](./determinismo.md).

## Lint y veredicto

- `runners/tc_lint.py` — linter del task-contract (anti-desvarío del autor).
- `runners/task_gate.py` — veredicto unificado: `tc_lint` + tests congelados + complejidad ≤ budget + gate-signature + deps opt-in + aprobación.

> Nota: los contratos KDD de `knowledge/contracts/` (formato híbrido OKF+CCDD) son validados por `scripts/validate_contracts.py`; los contratos nativos del repo viven bajo `contracts/` y son **intocables** (rúbricas firmadas Ed25519, ajenas a KDD).