"""Paquete `runners` de ccdd-gate: gate determinista, tc_lint, task_gate, métricas y el MCP.

Los módulos se importan entre sí por nombre simple (p.ej. `import tc_lint`) apoyándose en el
`sys.path.insert(parent)` que cada uno hace al cargarse — así funcionan igual ejecutados como
script (`python runners/x.py`) o como módulo del paquete instalado (`runners.x`)."""
