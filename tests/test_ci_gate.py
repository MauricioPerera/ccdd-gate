"""test_ci_gate.py — tests CONGELADOS del driver de CI (#12). Sin LLM. Sin red.

Aceptación de la issue:
  - PR con contrato roto o complejidad > budget ⇒ veredicto no-PASS (check rojo).
  - PR limpio ⇒ PASS con resumen de métricas.
  - descubre los contratos afectados (contrato cambiado o su código objetivo cambiado).
"""
import contextlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO / "integrations" / "github"))
import ci_gate  # noqa: E402
import reporter  # noqa: E402

SANDBOX = REPO / "examples" / "sandbox"

MINI_CONTRACT = """---
task: mini
intent: "x"
target: mod.py
signature: "def f(a)"
budget: { cyclomatic_max: 5 }
tests: t.py
---
# body
"""


class TestIsContract(unittest.TestCase):
    def test_recognizes_real_contract(self):
        self.assertTrue(ci_gate.is_contract(SANDBOX / "task.md"))

    def test_rejects_non_contract_md(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "readme.md").write_text("# just docs\n", encoding="utf-8")
            self.assertFalse(ci_gate.is_contract(d / "readme.md"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_rejects_non_md(self):
        self.assertFalse(ci_gate.is_contract(SANDBOX / "disassembler.py"))


class TestContractsForChanged(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "task.md").write_text(MINI_CONTRACT, encoding="utf-8")
        (self.d / "mod.py").write_text("def f(a):\n    return a\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_detects_changed_contract(self):
        found = ci_gate.contracts_for_changed(["task.md"], self.d)
        self.assertEqual([Path(p).name for p in found], ["task.md"])

    def test_detects_changed_target_code(self):
        found = ci_gate.contracts_for_changed(["mod.py"], self.d)
        self.assertEqual([Path(p).name for p in found], ["task.md"])

    def test_ignores_unrelated_changes(self):
        self.assertEqual(ci_gate.contracts_for_changed(["other.py"], self.d), [])


class TestVerdictAndReport(unittest.TestCase):
    def test_clean_contract_passes(self):
        results = ci_gate.run([SANDBOX / "task.md"])
        self.assertTrue(ci_gate.overall_pass(results))

    def test_broken_budget_fails(self):
        d = Path(tempfile.mkdtemp())
        try:
            shutil.copy(SANDBOX / "test_decode_instruction.py", d / "test_decode_instruction.py")
            shutil.copy(SANDBOX / "disassembler.py", d / "disassembler.py")
            t = (SANDBOX / "task.md").read_text(encoding="utf-8").replace("cyclomatic_max: 8", "cyclomatic_max: 1")
            (d / "task.md").write_text(t, encoding="utf-8")
            results = ci_gate.run([d / "task.md"])
            self.assertFalse(ci_gate.overall_pass(results))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_combined_report_single_marker(self):
        results = ci_gate.run([SANDBOX / "task.md"])
        body = ci_gate.combined_report(results)
        self.assertEqual(body.count(reporter.MARKER), 1)
        self.assertIn("PASS", body)

    def test_empty_results_report(self):
        body = ci_gate.combined_report([])
        self.assertIn(reporter.MARKER, body)
        self.assertIn("sin task-contracts", body)
        self.assertTrue(ci_gate.overall_pass([]))  # nada que fallar


class CompositionNoteTest(unittest.TestCase):
    def test_ok_no_note(self):
        self.assertEqual(ci_gate.composition_note({"ok": True}), "")

    def test_debt_renders_and_lists(self):
        audit = {"ok": False, "ungated_composition": [
            {"contract": "a.md", "composes": ["b", "c"]}]}
        note = ci_gate.composition_note(audit)
        self.assertIn("composición sin verificar (1)", note)
        self.assertIn("a.md", note)
        self.assertIn("b, c", note)


class AnnotationsAndMutationNotesTest(unittest.TestCase):
    def test_annotations_note(self):
        self.assertEqual(ci_gate.annotations_note({"ok": True}), "")
        note = ci_gate.annotations_note({"ok": False, "failures": [
            {"target": "aacs/x.py", "detail": "nombres ...: ['Node']"}]})
        self.assertIn("anotaciones sin resolver (1)", note)
        self.assertIn("aacs/x.py", note)
        self.assertIn("Node", note)

    def test_mutation_note(self):
        self.assertEqual(ci_gate.mutation_note([]), "")
        note = ci_gate.mutation_note([{"contract": "a.md", "survived": ["op@L13"]}])
        self.assertIn("mutantes sobrevivientes", note)
        self.assertIn("op@L13", note)


class PostingFailureTest(unittest.TestCase):
    """Un fallo de posting (gh read-only en PRs de fork) NO debe pisar el veredicto del
    gate: el exit code sigue al veredicto, no a la capacidad de comentar.

    Aislado del motor del gate: se mockea ci_gate.run con un veredicto controlado para
    NO depender de task_gate/sandbox (código en flujo paralelo). Lo que se prueba es el
    try/except alrededor de _maybe_post en main()."""

    def _ctx(self, verdict):
        mgrs = (
            patch.object(ci_gate, "_select_contracts", return_value=["dummy.md"]),
            patch.object(ci_gate, "run", return_value=[{"contract": "dummy.md", "verdict": {"verdict": verdict}}]),
            patch.object(ci_gate, "combined_report", return_value="body"),
            patch.object(ci_gate.audit_composition, "audit", return_value={"ok": True}),
            patch.object(ci_gate.audit_annotations, "audit", return_value={"ok": True}),
            patch.object(ci_gate, "mutation_survivors", return_value=[]),
            patch.object(ci_gate.reporter, "upsert_comment", side_effect=RuntimeError("gh read-only")),
        )
        return mgrs

    def _run(self, verdict):
        with contextlib.ExitStack() as stack:
            for m in self._ctx(verdict):
                stack.enter_context(m)
            return ci_gate.main(["dummy.md", "--post", "--repo", "o/r", "--issue", "1"])

    def test_posting_failure_keeps_pass_exit_zero(self):
        rc = self._run("PASS")
        self.assertEqual(rc, 0, "gate PASS + posting falla -> exit 0 (veredicto, no posting)")

    def test_posting_failure_keeps_fail_exit_one(self):
        rc = self._run("FAIL")
        self.assertEqual(rc, 1, "gate FAIL + posting falla -> exit 1 (veredicto, no posting)")


if __name__ == "__main__":
    unittest.main()
