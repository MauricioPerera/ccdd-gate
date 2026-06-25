---
task: eval-gate
intent: "Gatear el comportamiento NO determinista de un agente con un veredicto determinista."
issue: MauricioPerera/ccdd-gate#52
target: runners/eval_gate.py
tests: tests/test_eval_gate.py
spec_version: "0.1"
language: python
---

## Intent
El gate de complejidad/tests verifica CÓDIGO (funciones con oráculo independiente). Un agente de
producción (bot de soporte, asistente de research) produce texto/JSON NO determinista que ese gate
no cubre. Este pilar lo cierra sin renunciar al determinismo donde se puede, en dos niveles: Tier 1
determinista (sin LLM) y Tier 2 (juez LLM acotado, opt-in y auditado).

> Nota CCDD: el gate de código verifica CÓDIGO; el de evals verifica COMPORTAMIENTO. El veredicto
> Tier 1 es 100% reproducible; el juez Tier 2 no cuenta hasta pasar judge_audit.

## Interface
```
runners/eval_gate.py     gate(eval_path) -> {verdict, cases, passed, pass_rate, hard_violations, failing}
                         CLI: eval_gate.py eval.md  (exit 0 PASS · 1 FAIL · 2 INVALID)
runners/eval_checks.py   run_checks(output, case, enabled, schema) -> [violaciones]
                         checks: schema, must_contain, forbid_contains, must_cite, groundedness,
                                 no_pii, trajectory  (uno por función, determinista)
runners/approve_eval_cases.py   firma humana del dataset (cases_sha256, sobre bytes LF)
runners/eval_judge.py    juez Tier 2 (provider stub offline | openai temp 0)   [opt-in, único con LLM]
runners/judge_audit.py   acuerdo del juez vs golden set -> {agreement, ok}     [opt-in]
contracts/eval-agent/    rúbrica firmada del juez (system/policies/thresholds/env)
MCP: run_eval_gate(eval_path), eval_rubric(), judge_audit(eval_path)
eval-contract (front-matter): eval, intent, target, agent_entry, dataset, budget,
                              deterministic_checks, schema?, rubric?, judge{required,model,agreement_min}
```

## Invariants
- Dataset CONGELADO: si require_cases_approval, los bytes deben coincidir con cases_sha256 o INVALID.
- PASS ⟺ casos intactos ∧ pass_rate ≥ budget.pass_rate_min ∧ violaciones duras ≤ forbidden_violations_max.
- Violación dura = término prohibido, PII, cita a fuente inexistente (groundedness), tool prohibida.
- Tier 1 no llama a ningún LLM: mismo input → mismo veredicto. El juez Tier 2 es opt-in.
- judge_audit: si agreement < judge.agreement_min, falla el JUEZ (no el agente).

## Examples
- support-bot-refunds (ejemplo): 3 casos, agente determinista → run_eval_gate = PASS, pass_rate 1.0.
- agente que afirma lo prohibido / cita índice inexistente → FAIL con violación dura.
- dataset manipulado tras firmar → INVALID (cases-approval).
- judge_audit (provider stub) sobre el golden set → agreement 1.0, ok.

## Do / Don't
- DO: empujar a Tier 1 todo lo objetivable (schema, citas, PII, trayectoria); congelar y firmar el dataset.
- DON'T: dejar que el juez LLM decida el PASS/FAIL del agente sin pasar judge_audit; relajar el dataset sin re-firmar.

## Tests
`tests/test_eval_gate.py` (offline, sin LLM): PASS sobre el ejemplo, FAIL con agente roto, FAIL por
fuente alucinada, INVALID por dataset manipulado, output no-dict → FAIL controlado, schema inexistente
→ INVALID, unidad de checks (groundedness/trayectoria), y judge_audit con provider stub (agreement 1.0).

## Constraints
- Tier 1 sin LLM y determinista. No cambiar lint_results.schema.json.
- El juez Tier 2 se sirve con modelo pinneado y temperature 0; su veredicto se audita.
- PARAR y reportar si un caso no se puede resolver desde el contexto: el agente se abstiene, no alucina.
