"""test_issue_link.py — tests CONGELADOS del vínculo contrato<->issue (#11). Sin LLM. Sin red.

Aceptación de la issue:
  - contrato con `issue` válido pasa lint; con formato inválido falla tc-issue-ref.
  - link mapea en ambos sentidos (contrato->issue ref; issue->contratos que lo referencian).
  - el sync de labels es idempotente y no pisa labels ajenas.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO / "integrations" / "github"))
import tc_lint  # noqa: E402
import link  # noqa: E402

SANDBOX = REPO / "examples" / "sandbox"


def _contract_with(issue_line):
    """Copia el sandbox a un tempdir e inyecta líneas de front-matter. Devuelve (dir, task_path)."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(SANDBOX / "test_decode_instruction.py", d / "test_decode_instruction.py")
    text = (SANDBOX / "task.md").read_text(encoding="utf-8")
    if issue_line:
        text = text.replace("spec_version:", issue_line + "\nspec_version:", 1)
    (d / "task.md").write_text(text, encoding="utf-8")
    return d, d / "task.md"


def _rules(task, level):
    return {f["rule"] for f in tc_lint.lint(task) if f["level"] == level}


class TestIssueRefRule(unittest.TestCase):
    def test_valid_short_ref_passes(self):
        d, t = _contract_with('issue: "o/r#11"')
        try:
            self.assertNotIn("tc-issue-ref", _rules(t, "error"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_valid_url_passes(self):
        d, t = _contract_with('issue: "https://github.com/o/r/issues/11"')
        try:
            self.assertNotIn("tc-issue-ref", _rules(t, "error"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_invalid_format_errors(self):
        d, t = _contract_with('issue: "issue once"')
        try:
            self.assertIn("tc-issue-ref", _rules(t, "error"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_absent_issue_is_backcompat(self):
        d, t = _contract_with(None)  # sin issue -> no error, no warn
        try:
            self.assertNotIn("tc-issue-ref", _rules(t, "error"))
            self.assertNotIn("tc-issue-ref", _rules(t, "warn"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_require_issue_warns_when_missing(self):
        d, t = _contract_with("require_issue: true")
        try:
            self.assertIn("tc-issue-ref", _rules(t, "warn"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestParseAndNormalize(unittest.TestCase):
    def test_parse_short_and_url(self):
        self.assertEqual(link.parse_issue_ref("o/r#5"), ("o", "r", 5))
        self.assertEqual(link.parse_issue_ref("https://github.com/o/r/issues/5"), ("o", "r", 5))
        self.assertEqual(link.parse_issue_ref("https://github.com/o/r/pull/9"), ("o", "r", 9))

    def test_normalize_unifies_forms(self):
        self.assertEqual(link.normalize_issue_ref("https://github.com/o/r/issues/5"), "o/r#5")
        self.assertEqual(link.normalize_issue_ref("o/r#5"), "o/r#5")

    def test_bad_ref_raises(self):
        with self.assertRaises(ValueError):
            link.parse_issue_ref("nope")


class TestIssueToContracts(unittest.TestCase):
    def test_contracts_referencing_finds_both_forms(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "a.md").write_text('---\ntask: a\nissue: "o/r#7"\n---\n# a\n', encoding="utf-8")
            (d / "b.md").write_text('---\ntask: b\nissue: "https://github.com/o/r/issues/7"\n---\n# b\n', encoding="utf-8")
            (d / "c.md").write_text('---\ntask: c\nissue: "o/r#8"\n---\n# c\n', encoding="utf-8")
            (d / "d.md").write_text("no front matter\n", encoding="utf-8")
            found = {Path(p).name for p in link.contracts_referencing("o/r#7", d)}
            self.assertEqual(found, {"a.md", "b.md"})
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestLabels(unittest.TestCase):
    def test_state_to_labels(self):
        st = {"drafted": True, "lint_ok": True, "tests_approved": False, "gate_passed": False}
        self.assertEqual(link.state_to_labels(st), {"ccdd:drafted", "ccdd:lint-ok"})

    def test_diff_does_not_touch_foreign_labels(self):
        desired = {"ccdd:drafted", "ccdd:lint-ok"}
        add, remove = link.diff_labels(["bug", "ccdd:drafted", "ccdd:gate-passed"], desired)
        self.assertEqual(add, ["ccdd:lint-ok"])
        self.assertEqual(remove, ["ccdd:gate-passed"])  # 'bug' intacto

    def test_diff_is_idempotent(self):
        desired = {"ccdd:drafted", "ccdd:lint-ok"}
        add, remove = link.diff_labels(["bug", "ccdd:drafted", "ccdd:lint-ok"], desired)
        self.assertEqual((add, remove), ([], []))


class TestContractState(unittest.TestCase):
    def test_sandbox_state_lint_ok(self):
        st = link.contract_state(str(SANDBOX / "task.md"), run_gate=False)
        self.assertTrue(st["drafted"])
        self.assertTrue(st["lint_ok"])


if __name__ == "__main__":
    unittest.main()
