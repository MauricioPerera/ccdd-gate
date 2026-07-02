"""test_eval_gate.py — tests CONGELADOS del pilar de evals Tier 1 (eval_gate + eval_checks +
judge_audit con provider stub) + Tier 2 (política judge.required, auditoría no-stub). Sin LLM:
veredictos reproducibles corrida a corrida.

PASS usa el ejemplo estable (examples/eval/support-bot-refunds). Los casos FAIL/INVALID construyen
su propia variante en un tempdir (agente roto, dataset manipulado) — sin tocar el ejemplo."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import eval_gate    # noqa: E402
import eval_checks  # noqa: E402
import eval_judge   # noqa: E402
import judge_audit  # noqa: E402

EX = REPO / "examples" / "eval" / "support-bot-refunds"
EVAL = EX / "eval.md"
FILES = ("eval.md", "cases.jsonl", "response.schema.json", "support_bot.py")

# Agente roto: afirma lo prohibido, no cita, sin search_docs -> dispara violaciones duras y blandas.
BROKEN_AGENT = '''def answer(case_input):
    return {"text": "Si, puedes pedir el reembolso cuando quieras, sin limite.",
            "citations": [], "trajectory": ["compose"]}
'''

# Agente que alucina la fuente: cita un índice inexistente -> violación dura de groundedness.
HALLUCINATING_AGENT = '''def answer(case_input):
    return {"text": "No: el plazo de reembolso es de 30 dias y ya se supero.",
            "citations": [99], "trajectory": ["search_docs", "compose"]}
'''


def _variant(agent_text=None, append_case=None):
    d = Path(tempfile.mkdtemp())
    for f in FILES:
        shutil.copy(EX / f, d / f)
    if agent_text is not None:
        (d / "support_bot.py").write_text(agent_text, encoding="utf-8")
    if append_case is not None:
        cur = (d / "cases.jsonl").read_text(encoding="utf-8")
        (d / "cases.jsonl").write_text(cur + append_case + "\n", encoding="utf-8")
    return d


def _set_judge_required(d, required="true"):
    """Reescribe el front-matter del eval-contract copiado para forzar judge.required."""
    txt = (d / "eval.md").read_text(encoding="utf-8")
    txt = txt.replace("  required: false", f"  required: {required}")
    (d / "eval.md").write_text(txt, encoding="utf-8")
    return d


class EvalGateTier1(unittest.TestCase):
    def test_pass_on_example(self):
        v = eval_gate.gate(str(EVAL))
        self.assertEqual(v["verdict"], "PASS", v)
        self.assertEqual(v["pass_rate"], 1.0)
        self.assertEqual(v["hard_violations"], 0)

    def test_fail_broken_agent(self):
        d = _variant(agent_text=BROKEN_AGENT)
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertGreater(v["hard_violations"], 0)
        finally:
            shutil.rmtree(d)

    def test_fail_hallucinated_source(self):
        d = _variant(agent_text=HALLUCINATING_AGENT)
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "FAIL", v)
            checks = {x["check"] for r in v["failing"] for x in r["violations"]}
            self.assertIn("groundedness", checks)
        finally:
            shutil.rmtree(d)

    def test_non_dict_output_fails_gracefully(self):
        # El agente devuelve un str (no un objeto): debe ser FAIL controlado, no crash (AttributeError).
        d = _variant(agent_text='def answer(case_input):\n    return "no soy un dict"\n')
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertGreater(v["hard_violations"], 0)
        finally:
            shutil.rmtree(d)

    def test_invalid_missing_schema_file(self):
        # schema declarado pero ausente = typo en el contrato: INVALID explícito, no degradación silenciosa.
        d = _variant()
        try:
            (d / "response.schema.json").unlink()
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertEqual(v["stage"], "contract")
        finally:
            shutil.rmtree(d)

    def test_invalid_tampered_dataset(self):
        # Añadir un caso cambia los bytes del dataset -> el hash firmado no coincide -> INVALID.
        d = _variant(append_case='{"id": "injected", "input": {}}')
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertEqual(v["stage"], "cases-approval")
        finally:
            shutil.rmtree(d)

    def test_judge_required_without_audit_is_not_pass(self):
        # judge.required:true y sin auditoría válida del juez -> no PASS (INVALID, política Tier 2).
        d = _set_judge_required(_variant())
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertNotEqual(v["verdict"], "PASS", v)
            self.assertEqual(v["stage"], "judge-audit", v)
        finally:
            shutil.rmtree(d)

    def test_judge_required_with_signed_audit_passes_gate_judge(self):
        # judge.required:true + declaración firmada audit_valid:true -> la etapa judge-audit cede
        # (el veredicto final depende de Tier 1, pero el gate del juez no bloquea).
        d = _set_judge_required(_variant())
        try:
            txt = (d / "eval.md").read_text(encoding="utf-8")
            (d / "eval.md").write_text(txt.replace("  agreement_min: 0.85",
                                                   "  agreement_min: 0.85\n  audit_valid: true"),
                                       encoding="utf-8")
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertNotEqual(v["stage"], "judge-audit", v)
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(d)


class EvalChecksUnit(unittest.TestCase):
    def test_groundedness_flags_out_of_range_citation(self):
        case = {"input": {"context": ["doc0"]}}
        viol = eval_checks.check_groundedness({"citations": [0, 5]}, case)
        self.assertEqual(len(viol), 1)
        self.assertTrue(viol[0]["hard"])

    def test_trajectory_forbidden_tool_is_hard(self):
        case = {"trajectory": {"required_tools": ["a"], "forbidden_tools": ["b"], "max_steps": 2}}
        viol = eval_checks.check_trajectory({"trajectory": ["a", "b", "c"]}, case)
        kinds = {(v["detail"][:9], v["hard"]) for v in viol}
        self.assertTrue(any(v["hard"] for v in viol))  # tool prohibida
        self.assertGreaterEqual(len(viol), 2)          # prohibida + exceso de pasos

    def test_trajectory_normalizes_casing_and_spaces(self):
        # " Send_Email" con forbidden send_email -> violación dura (no se evade por casing/espacios).
        case = {"trajectory": {"forbidden_tools": ["send_email"]}}
        viol = eval_checks.check_trajectory({"trajectory": [" Send_Email", "search_docs"]}, case)
        self.assertEqual(len(viol), 1)
        self.assertTrue(viol[0]["hard"])
        self.assertIn("tool prohibida", viol[0]["detail"])

    def test_trajectory_required_tool_normalized(self):
        # required "Search_Docs" satisfecho por " search_docs " normalizado -> sin violación.
        case = {"trajectory": {"required_tools": ["Search_Docs"]}}
        viol = eval_checks.check_trajectory({"trajectory": [" search_docs "]}, case)
        self.assertEqual(viol, [])

    def test_no_pii_scans_citations_and_trajectory(self):
        # PII embebida en una cita-string (no en text) -> flaggeada.
        out = {"text": "ok", "citations": ["contacto: user@example.com"], "trajectory": []}
        viol = eval_checks.check_no_pii(out, {})
        self.assertEqual(len(viol), 1)
        self.assertTrue(viol[0]["hard"])

    def test_no_pii_flags_credit_card_and_phone(self):
        self.assertTrue(eval_checks.check_no_pii(
            {"text": "mi tarjeta es 4111 1111 1111 1111", "citations": [], "trajectory": []}, {}))
        self.assertTrue(eval_checks.check_no_pii(
            {"text": "llamame al +1 (555) 123-4567", "citations": [], "trajectory": []}, {}))

    def test_no_pii_ignores_normal_domain_digits(self):
        # Cifras del dominio ("30 dias") no son PII -> sin violación.
        out = {"text": "el plazo es de 30 dias", "citations": [0], "trajectory": ["search_docs"]}
        self.assertEqual(eval_checks.check_no_pii(out, {}), [])

    def test_forbid_contains_normalizes_accents(self):
        # forbid "sí, puedes" debe flaggear texto "Si, puedes" tras quitar acentos (y viceversa).
        case = {"expect": {"forbid_contains": ["sí, puedes"]}}
        viol = eval_checks.check_forbid_contains({"text": "Si, puedes pedirlo"}, case)
        self.assertEqual(len(viol), 1)
        self.assertTrue(viol[0]["hard"])

    def test_must_contain_normalizes_accents(self):
        case = {"expect": {"must_contain_any": ["días"]}}
        self.assertEqual(eval_checks.check_must_contain({"text": "dentro de 30 dias"}, case), [])


class JudgeAuditTests(unittest.TestCase):
    def test_stub_does_not_enable_tier2(self):
        # stub: acuerdo 1.0 (mecánica tautológica) PERO la auditoría NO habilita Tier 2.
        r = judge_audit.audit(str(EVAL), provider="stub")
        self.assertFalse(r["ok"], r)
        self.assertFalse(r["audit_valid"], r)
        self.assertEqual(r["agreement"], 1.0)
        self.assertEqual(r["golden_cases"], 3)
        self.assertEqual(r["provider"], "stub")
        self.assertIsNotNone(r.get("note"))

    def test_discrepant_judge_fails_audit(self):
        # Juez fake que siempre disiente del golden -> acuerdo 0 < min -> ok=False, audit_valid=False.
        fake = lambda out, c: {"verdict": "fail", "score": 0, "provider": "fake"}
        r = judge_audit.audit(str(EVAL), provider="fake", judge_fn=fake)
        self.assertFalse(r["ok"], r)
        self.assertFalse(r["audit_valid"], r)
        self.assertLess(r["agreement"], r["agreement_min"])

    def test_unknown_provider_raises(self):
        # provider desconocido -> error explícito, NO fallback mudo a stub.
        with self.assertRaises(ValueError):
            eval_judge.judge({"text": "x"}, {"golden_judgment": {"verdict": "pass"}},
                             "rubrica", provider="no-existe")


if __name__ == "__main__":
    unittest.main()