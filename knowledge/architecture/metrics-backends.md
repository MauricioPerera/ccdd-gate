---
type: 'Architecture'
title: 'Backends de métricas'
description: 'Capa neutral de métricas: backend Python AST nativo + backends tree-sitter (13 lenguajes) y el oráculo de conformancia congelado.'
tags: ['architecture', 'metrics', 'tree-sitter', 'conformancia']
---

# Backends de métricas

Las cuatro métricas de complejidad (ciclomática, anidamiento, aridad, longitud) son independientes del lenguaje; solo la **extracción** (parsear y contar) varía. Este nodo describe la capa que las enruta. El formato de este nodo se define en [OKF-SPEC](../OKF-SPEC.md); encaja en la [Arquitectura general](./overview.md).

## Capa neutral

- `runners/metrics_backends.py` — define la métrica neutral, los **umbrales firmados** y `severity()` compartidos por todos los lenguajes, el ensamblado de `lint_results` y el registro `get_backend(language|extension|filename)`. Añadir un lenguaje = registrar un backend sin tocar gate/runner/MCP.

Umbrales CRÍTICA (espejo del contrato firmado `contracts/complexity-agent`): `cyclomatic ≥ 21`, `nesting_depth ≥ 5`. El gate duro bloquea solo en CRÍTICA; ALTA reporta, no bloquea.

## Backend Python nativo

- `runners/metrics.py` — backend Python por AST nativo (sin dependencias). Es el baseline y siempre está disponible.

## Backends tree-sitter (13 lenguajes)

- `runners/metrics_treesitter.py` — backend universal vía tree-sitter: TypeScript, TSX, JavaScript, Rust, Go, Java, C#, PHP, Ruby, Kotlin, C, Swift y C++ (13 backends tree-sitter + Python nativo = 14 lenguajes). Es una **dependencia opcional**: si las gramáticas no están instaladas, esos archivos son un no-op anunciado (aviso por stderr, exit 0), nunca un fallo silencioso.

## Oráculo de conformancia congelado

- `fixtures/conformance/manifest.json` — oráculo congelado de las 4 métricas: fixtures equivalentes por lenguaje + valores esperados. Todo backend debe reproducirlo; los backends tree-sitter pasan `tests/test_conformance.py` con métricas estructurales idénticas (`cyclomatic`/`nesting_depth`/`parameter_count`); solo `function_length` diverge por formato y se fija por-lenguaje.
- Regla de cambio: **solo aditivos**. Un backend nuevo no se acepta hasta pasar la suite de conformancia; los valores esperados del oráculo no se retocan para acomodar un backend (ver `fixtures/conformance/README.md`).

## Límites

Los checks de antipatrones (`gate-mutdef`, `gate-assert`, `gate-signature`, `gate-deps`, etc.) siguen siendo **Python-only** (AST nativo). El multi-lenguaje cubre solo las métricas de complejidad.