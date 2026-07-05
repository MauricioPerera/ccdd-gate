# Knowledge Bundle (OKF) — ccdd-gate

Bienvenido a la base de conocimiento de ccdd-gate. El formato de los nodos está especificado en [OKF-SPEC](./OKF-SPEC.md). El repositorio implementa la metodología **KDD (Knowledge-Driven Development)**: OKF para modelar el conocimiento + CCDD para gobernar el desarrollo con gates deterministas.

## Referencia
- [Especificación OKF](./OKF-SPEC.md) — spec normativa de nodos OKF.

## Arquitectura
- [Arquitectura general](./architecture/overview.md) — los dos pilares (gate de código + evals), el servidor MCP y el flujo task-contract → lint → gate → veredicto.
- [Backends de métricas](./architecture/metrics-backends.md) — capa neutral, backend Python AST nativo, backends tree-sitter (9 lenguajes) y el oráculo de conformancia congelado.

## Conceptos
- [Task-contract](./concepts/task-contract.md) — el contrato CCDD nativo: frontmatter, 7 secciones, tests congelados con sha256 y budget firmado.
- [Determinismo](./concepts/determinismo.md) — el principio rector: árbitro insobornable sin LLM, versiones pineadas, salidas ordenadas, firmas Ed25519.

## Contratos
- [Contratos KDD](./contracts/) — task-contracts híbridos OKF+CCDD para agentes efímeros (validados por `scripts/validate_contracts.py`).