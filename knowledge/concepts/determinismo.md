---
type: 'Concept'
title: 'Determinismo'
description: 'El principio rector: árbitro insobornable sin LLM, versiones pineadas, salidas ordenadas y firmas Ed25519.'
tags: ['concept', 'determinismo', 'ed25519', 'principio']
---

# Determinismo

El principio rector de ccdd-gate: **mismo input → mismo veredicto, corrida a corrida**. El control y el veredicto viven en código que no se puede engañar; la inteligencia difusa va en el LLM. El formato de este nodo se define en [OKF-SPEC](../OKF-SPEC.md); gobierna al [Task-contract](./task-contract.md) y a la [Arquitectura general](../architecture/overview.md).

## El árbitro es insobornable (sin LLM en el veredicto)

El sustrato determinista **no llama a ningún LLM**. El cerebro es el agente anfitrión (Claude Code, Cursor, etc.) que invoca las herramientas; el gate mide y decide. La condición de parada no es el juicio del modelo — es un veredicto determinista (complejidad ≤ budget firmado + property-tests congelados).

## Versiones pineadas

Las dependencias externas se pinean exacto para que el veredicto no derive con el entorno:

- `runners/linter_gate.py` exige `version` pin exacto (hoy `ruff==0.15.20`); versión instalada ≠ pin → entorno inválido (exit 2, **no es PASS**).
- El oráculo de conformancia (`fixtures/conformance/manifest.json`) es congelado; cambios solo aditivos (ver [Backends de métricas](../architecture/metrics-backends.md)).

## Salidas ordenadas

Los findings siguen un orden canónico fijo (`METRIC_KEYS` en `runners/metrics_backends.py`): determinismo y regresión cero. Idempotente corrida a corrida.

## Firmas Ed25519

La gobernanza L2 se atestá con firmas Ed25519 de revisores (gate de aprobación byte-exacto sobre tests y datasets). Es lo que vuelve no manipulables los `tests_sha256` / `cases_sha256` — ver [Task-contract](./task-contract.md).

## Dónde se materializa

- `runners/task_gate.py` — veredicto unificado (tests congelados + complejidad ≤ budget + firma).
- `runners/linter_gate.py` — linters externos pineados como checks opt-in.
- `fixtures/conformance/` + `tests/test_conformance.py` — conformancia multi-lenguaje contra el oráculo congelado.