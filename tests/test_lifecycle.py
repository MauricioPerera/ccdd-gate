"""test_lifecycle.py — tests CONGELADOS del orquestador<->ciclo de vida del issue (#14). Sin red.

Aceptación de la issue:
  - un issue ccdd:ready con contrato válido produce un PR enlazado cuando el gate pasa (acción open_pr).
  - las transiciones de label son deterministas y reversibles.
  - sin la integración, el orquestador corre igual en local (callback opcional, default None).
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO / "integrations" / "github"))
import lifecycle as lc  # noqa: E402
import orchestrator  # noqa: E402

BROKEN = "---\ntask: x\nintent: hace y ademas otra\nbudget: {cyclomatic_max: 999}\n---\n# sin secciones\n"


class TestDecideTransition(unittest.TestCase):
    def test_deterministic_mapping(self):
        self.assertEqual(lc.decide_transition({"result": "PASS"})["action"], "open_pr")
        self.assertEqual(lc.decide_transition({"result": "PASS"})["label"], "ccdd:in-review")
        self.assertEqual(lc.decide_transition({"result": "ESCALATE"})["label"], "ccdd:escalated")
        self.assertEqual(lc.decide_transition({"result": "FAIL"})["label"], "ccdd:needs-split")
        self.assertEqual(lc.decide_transition({"result": "INVALID"})["label"], "ccdd:needs-split")

    def test_unknown_result_safe_default(self):
        self.assertEqual(lc.decide_transition({"result": "???"})["action"], "comment_invalid")


class TestLabelTransition(unittest.TestCase):
    def test_removes_ready_adds_target_keeps_foreign(self):
        add, remove = lc.label_transition(["bug", "ccdd:ready", "ccdd:lint-ok"], "ccdd:in-review")
        self.assertEqual(add, ["ccdd:in-review"])
        self.assertEqual(remove, ["ccdd:ready"])  # 'bug' y 'ccdd:lint-ok' intactos

    def test_idempotent(self):
        self.assertEqual(lc.label_transition(["ccdd:in-review"], "ccdd:in-review"), ([], []))

    def test_reversible_swaps_only_lifecycle(self):
        # de in-review a escalated: quita in-review, pone escalated
        add, remove = lc.label_transition(["ccdd:in-review", "feature"], "ccdd:escalated")
        self.assertEqual(add, ["ccdd:escalated"])
        self.assertEqual(remove, ["ccdd:in-review"])


class TestReadyRefs(unittest.TestCase):
    def test_filters_ready_label(self):
        issues = [{"number": 5, "labels": [{"name": "ccdd:ready"}]},
                  {"number": 6, "labels": ["other"]},
                  {"number": 7, "labels": ["ccdd:ready"]}]
        self.assertEqual(lc.ready_refs(issues, "o/r"), ["o/r#5", "o/r#7"])


class TestProcessDryRun(unittest.TestCase):
    def test_pass_plans_open_pr(self):
        steps = lc.process({"result": "PASS", "task": "t",
                            "verdict": {"verdict": "PASS", "stage": "all"}}, "o/r#5", branch="feat/x")
        self.assertEqual(steps["decision"]["action"], "open_pr")
        self.assertIn("pr_preview", steps)
        self.assertIn("Closes #5", steps["pr_preview"])
        self.assertEqual(steps["labels"]["dry_run"], True)

    def test_escalate_plans_comment(self):
        steps = lc.process({"result": "ESCALATE", "task": "t"}, "o/r#5")
        self.assertEqual(steps["decision"]["label"], "ccdd:escalated")
        self.assertIn("comment_preview", steps)


class TestOrchestratorCallback(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "task.md").write_text(BROKEN, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_callback_fires_with_result(self):
        seen = {}
        orchestrator.implement(str(self.d / "task.md"), "stub", "m", 1, None, 1, iter([]),
                               on_result=lambda r, tp: seen.update(r))
        self.assertEqual(seen.get("result"), "INVALID")

    def test_default_no_callback_unchanged(self):
        res = orchestrator.implement(str(self.d / "task.md"), "stub", "m", 1, None, 1, iter([]))
        self.assertEqual(res["result"], "INVALID")  # local idéntico sin callback


if __name__ == "__main__":
    unittest.main()
