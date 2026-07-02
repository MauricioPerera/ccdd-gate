# RB3 — Reparación del pilar de evals (Tier 2 tautológico + checks Tier 1 evadibles)

Rama: `audit-repairs` · Alcance: `runners/judge_audit.py`, `runners/eval_judge.py`,
`runners/eval_gate.py`, `runners/eval_checks.py`, `tests/test_eval_gate.py`.

## 1. [ALTO] Juez Tier 2 tautológico — FIX

**Bug:** `eval_judge.judge_stub` devuelve el `golden_judgment` del caso, así que con `provider=="stub"`
(default de la CLI de `judge_audit`) el acuerdo es 1.0 por construcción → `ok=true` siempre. La
promesa "el juez no cuenta hasta pasar judge_audit contra el golden set" se cumplía trivialmente.
Además `eval_judge.judge` caía a `judge_stub` en silencio ante un provider desconocido
(`PROVIDERS.get(provider, judge_stub)`), enmascarando typos del contrato como "juez calibrado".

**Fix `judge_audit.py`:**
- `audit()` adiciona `judge_fn` (solo para tests que simulan un juez discrepante; en producción se
  usa `eval_judge.judge`).
- Nuevo `_audit_verdict()` compone el veredicto con `audit_valid = (provider != "stub") and n>0
  and agreement >= minimum`. **stub → `audit_valid=false` y `ok=false`** con `note` explícita:
  *"provider 'stub' solo ejercita la mecánica (acuerdo 1.0 tautológico); NO habilita Tier 2. Use un
  provider real (openai) y re-corra la auditoría."* El campo `agreement` sigue calculándose (1.0
  para stub) para ejercitar la mecánica, pero la auditoría **no habilita Tier 2**.
- CLI: `return 0 if r["ok"] else 1` → stub ahora sale con código 1 (acuerdo insuficiente / stub).
- Helpers extraídos (`_score_case`, `_missing_keys`, `_audit_verdict`) para mantener
  `audit` bajo budget (cyclomatic=9, ≤10).

**Fix `eval_judge.py`:**
- `judge()` ahora raisea `ValueError` explícito ante provider no soportado (lista los soportados).
  **No hay fallback mudo a stub.**

## 2. [MEDIO] Tier 2 no se integraba en eval_gate; `judge.required` no lo enforceaba nadie — FIX

**Bug:** `eval_gate.gate` solo corría Tier 1 e ignoraba `fm["judge"]`. Un contrato que declaraba
`judge.required: true` podía PASS sin que el juez hubiera sido calibrado.

**Fix `eval_gate.py`:** nuevo `_gate_judge(fm, p)` insertado tras el gate de casos. Si
`judge.required: true`, exige evidencia de auditoría válida (no-stub) — sea declaración firmada
`judge.audit_valid: true` en el front-matter, sea artefacto `judge.audit` (ruta relativa) con
`audit_valid: true` y `provider != "stub"` (`_audit_artifact_valid`). Sin evidencia →
`INVALID` / `stage: "judge-audit"` con detalle claro. **El gate no llama al LLM**; enforza la
política. El ejemplo (`judge.required: false`) sigue PASS.

## 3. [MEDIO] Checks Tier 1 evadibles — FIX (`eval_checks.py`)

- **trajectory:** comparación de tools normalizada (`_norm` = strip+lower) en ambos lados.
  `" Send_Email"` / `"Send_Email"` / `"send_email"` son la misma tool → ni evaden
  `forbidden_tools` ni eluden `required_tools`.
- **no_pii:** `PII_PATTERNS` extendido (email, SSN-US, tarjeta de crédito 13-16 dígitos, teléfono
  internacional 10+ dígitos; patrones conservadores para no flaggear "30 dias"). `_pii_payload`
  escanea `output.text` + cualquier string en `citations`/`trajectory` (los ints se ignoran).
- **forbid_contains / must_contain:** ahora usan `_fold` (strip+lower+acentos quitados):
  insensible a mayúsculas, espacios y diacríticos (`"Sí"=="si"`, `"días"=="dias"`).
- **groundedness:** sin cambio de lógica; docstring reescrito para declarar honestamente que valida
  EXISTENCIA de la fuente citada, NO que la fuente SOSTENGA el texto (eso es Tier 2).

## Definición de hecho — verificación

Tests nuevos en `tests/test_eval_gate.py` (20 total, todas verdes):

1. `test_stub_does_not_enable_tier2` — stub: `ok=false`, `audit_valid=false`, `agreement=1.0`,
   `note` presente.
2. `test_discrepant_judge_fails_audit` — juez fake que siempre disiente → `agreement=0 < min`,
   `ok=false`, `audit_valid=false` (prueba que judge_audit SÍ falla a un juez malo).
3. `test_judge_required_without_audit_is_not_pass` — `judge.required:true` sin auditoría →
   no-PASS, `stage="judge-audit"`.
4. `test_trajectory_normalizes_casing_and_spaces` — `" Send_Email"` con forbidden `send_email`
   → violación dura.
5. `test_unknown_provider_raises` — provider desconocido → `ValueError`.

Adicionales: `test_judge_required_with_signed_audit_passes_gate_judge`,
`test_trajectory_required_tool_normalized`, `test_no_pii_scans_citations_and_trajectory`,
`test_no_pii_flags_credit_card_and_phone`, `test_no_pii_ignores_normal_domain_digits`,
`test_forbid_contains_normalizes_accents`, `test_must_contain_normalizes_accents`.

### Salida de la suite (tests/test_eval_gate.py — MI alcance)
```
....................                                                     [100%]
20 passed in 1.18s
```

### `python runners/eval_gate.py examples/eval/support-bot-refunds/eval.md`
```json
{
  "verdict": "PASS",
  "stage": "tier1-checks",
  "cases": 3,
  "passed": 3,
  "pass_rate": 1.0,
  "hard_violations": 0,
  "budget": { "pass_rate_min": 1.0, "forbidden_violations_max": 0 },
  "failing": []
}
```

### `python runners/judge_audit.py examples/eval/support-bot-refunds/eval.md` (stub)
`audit_valid: false`, `ok: false`, `note` explicativa, `agreement: 1.0`, `golden_cases: 3`,
`provider: "stub"`. Exit code: **1** (stub no habilita Tier 2).

## Estado de la suite COMPLETA — HONESTO

`python -m pytest tests/ -q` → **15 failed, 411 passed** (dos corridas, idénticas).

**Las 15 fallas NO son mías** y NO están en mi alcance de aislamiento. Todas viven en código que la
consigna marcabade como "NO toques" o que no estaba en mi lista, y que **devs en paralelo** están
modificando en este working tree (WIP no terminado):

- `tests/test_gates.py` (TestTaskGate, TestRunIntegrationGate) — ejercita `task_gate.py` /
  `run_integration_gate` (modificado por otro dev).
- `tests/test_orchestrator_cefl.py` — orchestrator (otro dev).
- `tests/test_rebind_bypass.py` — rebind gate (otro dev).
- `tests/test_reporter.py::test_pass_has_metrics_table` — reporter (otro dev); falla por
  `tests_sha256` que no coincide (WIP de `approve_tests.py` / `tc_lint.py`).

Verificado: al revertir **solo mis 5 archivos** a HEAD (dejando el WIP paralelo), las 15 fallas
**persisten** → son 100% del WIP paralelo, no de mis cambios. Al stash de **todo** el working tree
(árbol limpio a `9eeb3c0`), la suite pasa. Mis 20 tests de eval pasan con y sin mi código de
producción aplicado (los nuevos tests fallarían contra el código original — son los que prueban el
fix).

**No puedo dejar la suite COMPLETA en 0 failures sin tocar archivos fuera de mi alcance**
(`task_gate.py`, `complexity_gate.py`, `repo_gate.py`, `review_attestations.py`, `rules_gate.py`,
`tc_lint.py`, `approve_tests.py`, `ci_gate.py`, orchestrator, reporter, rebind) — exactamente lo
que la regla de aislamiento prohíbe. Per la consigna: *"Si algo no se puede sin romper otra área,
PARA y reporta."* — esto se reporta acá. Mis 4 archivos + `test_eval_gate.py` están en verde y
coherentes con la nota de `complexity_mcp.py` (el servidor fija provider/api_url por entorno).

## Complejidad (budget: cyclomatic≤10, nesting≤3, lines≤41)
- `audit` cyclomatic=9, lines=21 ✓
- `_gate_judge` cyclomatic=6 ✓ ; `_audit_artifact_valid` nesting=2 ✓
- `check_trajectory` cyclomatic=10 ✓ ; `_pii_payload` nesting=3 ✓
- Todas las funciones nuevas/modificadas bajo budget (verificado con `measure_complexity`).