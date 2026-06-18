"""test_reporter.py — tests CONGELADOS del reporter (#13). Sin LLM. Sin red.

Aceptación de la issue:
  - dado un JSON de veredicto, genera el mismo comentario (determinista).
  - re-ejecutar actualiza el comentario existente (selección por marker), no crea otro.
  - funciona offline (genera markdown) y online (la lógica de upsert es testeable sin red).
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "integrations" / "github"))
sys.path.insert(0, str(REPO / "runners"))
import reporter  # noqa: E402
import task_gate  # noqa: E402

PASS = task_gate.gate(str(REPO / "examples" / "sandbox" / "task.md"))
FAIL1 = {"verdict": "FAIL", "stage": "gate1-complexity", "function": "f",
         "over_budget": ["cyclomatic=12 > cyclomatic_max=8"]}
FAIL2 = {"verdict": "FAIL", "stage": "gate2-tests", "detail": "property-tests fallaron",
         "output": "AssertionError: boom\n" * 3}
INVALID = {"verdict": "INVALID", "stage": "contract", "detail": "el task-contract no lintea"}


class TestRenderDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        self.assertEqual(reporter.render(PASS), reporter.render(PASS))

    def test_no_timestamp_or_nondeterminism(self):
        # dos renders de un FAIL idéntico deben ser byte-iguales (no hay timestamps)
        self.assertEqual(reporter.render(FAIL2), reporter.render(FAIL2))

    def test_marker_present_at_top(self):
        self.assertTrue(reporter.render(PASS).startswith(reporter.MARKER))


class TestRenderContent(unittest.TestCase):
    def test_pass_has_metrics_table(self):
        md = reporter.render(PASS)
        self.assertIn("PASS", md)
        self.assertIn("| métrica | valor | budget |", md)
        self.assertIn("cyclomatic", md)

    def test_fail_gate1_lists_over_budget(self):
        md = reporter.render(FAIL1)
        self.assertIn("FAIL", md)
        self.assertIn("cyclomatic=12 > cyclomatic_max=8", md)

    def test_fail_gate2_includes_output(self):
        md = reporter.render(FAIL2)
        self.assertIn("property-tests fallaron", md)
        self.assertIn("AssertionError", md)

    def test_invalid_header(self):
        self.assertIn("INVALID", reporter.render(INVALID))

    def test_contract_link_optional(self):
        self.assertNotIn("Contrato:", reporter.render(PASS))
        self.assertIn("task.md", reporter.render(PASS, contract="path/task.md"))


class TestUpsertSelection(unittest.TestCase):
    def test_finds_existing_marked_comment(self):
        comments = [{"id": 1, "body": "hola"},
                    {"id": 7, "body": "x " + reporter.MARKER + " y"}]
        self.assertEqual(reporter.find_marked_comment(comments), 7)

    def test_returns_none_when_absent(self):
        self.assertIsNone(reporter.find_marked_comment([{"id": 1, "body": "sin marker"}]))

    def test_first_match_wins(self):
        comments = [{"id": 3, "body": reporter.MARKER}, {"id": 4, "body": reporter.MARKER}]
        self.assertEqual(reporter.find_marked_comment(comments), 3)


if __name__ == "__main__":
    unittest.main()
