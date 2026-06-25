"""test_eval_gate.py — tests CONGELADOS del pilar de evals Tier 1 (eval_gate + eval_checks +
judge_audit con provider stub). Sin LLM: veredictos reproducibles corrida a corrida.

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

    def test_invalid_tampered_dataset(self):
        # Añadir un caso cambia los bytes del dataset -> el hash firmado no coincide -> INVALID.
        d = _variant(append_case='{"id": "injected", "input": {}}')
        try:
            v = eval_gate.gate(str(d / "eval.md"))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertEqual(v["stage"], "cases-approval")
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


class JudgeAuditStub(unittest.TestCase):
    def test_stub_agreement_is_total(self):
        # El provider stub devuelve el golden_judgment: acuerdo 1.0 por construcción (mecánica).
        r = judge_audit.audit(str(EVAL), provider="stub")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["agreement"], 1.0)
        self.assertEqual(r["golden_cases"], 3)


if __name__ == "__main__":
    unittest.main()
