---
eval: support-bot-refunds
intent: "responde dudas de reembolso ancladas solo en el contexto provisto"
target: support_bot.py
agent_entry: answer
dataset: cases.jsonl
schema: response.schema.json
require_cases_approval: true
budget:
  pass_rate_min: 1.0
  forbidden_violations_max: 0
deterministic_checks: ["schema", "must_contain", "forbid_contains", "must_cite", "groundedness", "no_pii", "trajectory"]
rubric: eval-agent
judge:
  required: false
  model: "claude-haiku-4-5-20251001"
  agreement_min: 0.85
spec_version: "0.1"
cases_sha256: "11b0bdd0a729f57a421d69225cca2352a3e0a3b76fede48fb527d46a99b421de"
---

## Intent
El agente de soporte responde preguntas de reembolso usando ÚNICAMENTE el contexto provisto en
cada caso. Éxito: pasa los checks deterministas (Tier 1) sobre el dataset congelado; el juez LLM
(Tier 2) queda opt-in (`judge.required: false`) hasta que se decida activarlo.

## Interface
- `answer(input: dict) -> dict` con `input = {query: str, context: list[str]}`.
- Output: `{text: str, citations: list[int], trajectory: list[str]}` (ver `response.schema.json`).
- `citations` son índices del `context`: citar una fuente inexistente es violación dura (anti-alucinación).

## Checks (Tier 1, deterministas, sin LLM)
- `schema`: el output valida contra `response.schema.json`.
- `must_contain` / `forbid_contains`: presencia/ausencia de términos por caso.
- `must_cite` + `groundedness`: si el caso lo exige, hay citas y todas apuntan a fuentes existentes.
- `no_pii`: el texto no expone email/identificadores.
- `trajectory`: tools requeridas presentes, prohibidas ausentes, largo ≤ max_steps.

## Dataset
`cases.jsonl` (un caso por línea), CONGELADO y firmado con `cases_sha256`. Cambiarlo invalida la
aprobación hasta re-firmar con `approve_eval_cases.py`. Cada caso lleva `golden_judgment` atestado
por humano: lo usa `judge_audit.py` para calibrar al juez, no para graduar al agente.

## Budget
- `pass_rate_min: 1.0` — todos los casos deben pasar Tier 1.
- `forbidden_violations_max: 0` — cero violaciones duras (términos prohibidos, PII, alucinación de fuentes, tool prohibida).

## Tier 2 (opt-in)
`judge.required: false`. Para activar el juez LLM: pinear `judge.model`, correr `judge_audit.py`
contra el golden set y exigir `agreement ≥ judge.agreement_min` antes de que sus veredictos cuenten.

## Constraints
- NO modificar el dataset sin re-firmar (`approve_eval_cases.py`).
- El agente lee la ventana de reembolso del contexto; NO debe inventarla.
- PARAR y reportar si un caso no se puede resolver desde el contexto: el agente se abstiene, no alucina.
