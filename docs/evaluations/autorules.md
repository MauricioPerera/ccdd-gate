# Evaluación: autorules → ccdd-gate

Registro de la evaluación de [markwylde/autorules](https://github.com/markwylde/autorules) y qué de su
filosofía se adoptó en ccdd-gate (con beneficio real) y qué se descartó (y por qué).

## Qué es autorules
Checker de calidad de código por IA. Reglas declaradas en **Markdown natural** (`title` + `files:`
glob + criterio en prosa); un **LLM** (vía OpenRouter) evalúa cada archivo contra cada regla, en
workers paralelos, y produce un **reporte HTML** con costo/tokens. TypeScript, `npm install -g autorules`.

Filosofía: *reglas declarativas en lenguaje natural · juez LLM · barrido project-wide por glob ·
reporte ergonómico*.

## El choque de fondo
El corazón de autorules —**LLM como árbitro**— es lo **opuesto** a ccdd-gate, cuyo principio es un
**veredicto determinista e insobornable** (sin LLM en el verdict). Adoptar el juez LLM como veredicto
contradiría la razón de ser de ccdd-gate. (Si en algún momento se quiere juzgar reglas "difusas",
eso ya vive en el pilar de evals **Tier 2**, un juez LLM acotado y auditado contra un golden set.)

## Lo que se ADOPTÓ (beneficio real)
**El modelo declarativo "regla + glob", desacoplado del juez.** ccdd-gate tenía un hueco real: los
gates de antipatrón (`bare_except`, `assert`, `none_eq`, `mutable_defaults`, `purity`) **solo se
disparaban por contrato** (campos opt-in sobre el target de un task-contract); no había forma de
aplicarlos **project-wide**.

Tomando de autorules **solo el formato declarativo glob→regla** (no el LLM), se implementó
`runners/rules_gate.py` (#73): lee un `rules.yaml` (lista de `{check, files}`) y corre el check
**determinista** (AST) sobre cada función de los archivos que matchean el glob. Resultado: los
antipatrones pasan a ser **política de repo**, no solo por función gateada.

```yaml
# rules.yaml — ergonomía de autorules + árbitro insobornable de ccdd-gate
- check: bare_except
  files: "src/**/*.py"
- check: mutable_defaults
  files: "**/*.py"
```

Diferencia clave que se preservó: **el árbitro es AST determinista, no un LLM.** Misma entrada →
mismo veredicto. (autorules: juez LLM, no determinista.)

## Lo que se DESCARTÓ (y por qué)
- **Juez LLM como verdict**: no — mata el determinismo que define a ccdd-gate. Cubierto por evals
  Tier 2 si hiciera falta lo difuso.
- **Reporte HTML + tracking de costo/tokens**: bajo valor incremental — ya hay veredicto JSON, el
  reporter de la integración GitHub y `repo_gate`. No se priorizó.

## Resultado
- Implementado: `runners/rules_gate.py` + tool MCP `run_rules_gate` + `examples/rules.yaml.example`
  + tests congelados (`tests/test_rules_gate.py`). Ver la sección "Reglas project-wide por glob" del
  README.
- Crédito de la idea declarativa: autorules. Implementación determinista: ccdd-gate.
