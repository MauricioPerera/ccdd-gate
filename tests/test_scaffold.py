"""test_scaffold.py — tests CONGELADOS del scaffold from_issue (#10). Sin LLM. Sin red.

Aceptación de la issue:
  - produce un contrato que tc_lint reporta como INCOMPLETO de forma clara (placeholders),
    no uno falsamente verde.
  - funciona offline (con un JSON de issue pegado), sin red/credenciales.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO / "integrations" / "github"))
import tc_lint  # noqa: E402
import scaffold  # noqa: E402

ISSUE = {
    "title": "feat: runner de métricas para Rust",
    "body": "Necesitamos medir .rs\n\n## Detalle\nblah",
    "number": 99,
    "labels": [{"name": "ccdd"}, {"name": "enhancement"}],
    "html_url": "https://github.com/MauricioPerera/ccdd-gate/issues/99",
}


def lint_text(md):
    d = Path(tempfile.mkdtemp())
    (d / "task.md").write_text(md, encoding="utf-8")
    try:
        return tc_lint.lint(d / "task.md")
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


class TestKebab(unittest.TestCase):
    def test_kebab_deterministic(self):
        self.assertEqual(scaffold.kebab("Hello World!"), "hello-world")
        self.assertEqual(scaffold.kebab("feat: A  B"), "feat-a-b")
        self.assertEqual(scaffold.kebab(""), "task")


class TestNormalizeRef(unittest.TestCase):
    def test_prefers_html_url(self):
        self.assertEqual(scaffold.normalize_ref(ISSUE), ISSUE["html_url"])

    def test_falls_back_to_repo_number(self):
        self.assertEqual(scaffold.normalize_ref({"number": 7}, repo="o/r"), "o/r#7")

    def test_none_when_no_info(self):
        self.assertIsNone(scaffold.normalize_ref({"number": 7}))


class TestScaffoldContent(unittest.TestCase):
    def setUp(self):
        self.md = scaffold.scaffold(ISSUE)

    def test_has_base_frontmatter(self):
        self.assertIn("task: feat-runner", self.md)
        self.assertIn('intent: "feat: runner de métricas para Rust"', self.md)
        self.assertIn('issue: "https://github.com/MauricioPerera/ccdd-gate/issues/99"', self.md)
        self.assertIn("budget:", self.md)

    def test_has_all_sections(self):
        for header in ("## Intent", "## Interface", "## Invariants", "## Examples",
                       "## Do / Don't", "## Tests", "## Constraints"):
            self.assertIn(header, self.md)

    def test_imports_issue_body_as_context(self):
        self.assertIn("Necesitamos medir .rs", self.md)


class TestScaffoldIsIncompleteNotGreen(unittest.TestCase):
    def test_lint_reports_incomplete(self):
        findings = lint_text(scaffold.scaffold(ISSUE))
        errors = {f["rule"] for f in findings if f["level"] == "error"}
        self.assertTrue(errors, "el esqueleto NO debe ser falsamente verde")
        # placeholders explícitos -> firma y tests incompletos
        self.assertIn("tc-signature-valid", errors)
        self.assertIn("tc-tests-frozen", errors)

    def test_issue_ref_is_valid_format(self):
        # el campo issue generado debe ser válido (no añade un error de formato)
        findings = lint_text(scaffold.scaffold(ISSUE))
        self.assertNotIn("tc-issue-ref", {f["rule"] for f in findings})

    def test_offline_from_dict_no_network(self):
        # scaffold opera sobre un dict (JSON pegado) sin tocar la red
        md = scaffold.scaffold({"title": "x", "number": 1}, repo="o/r")
        self.assertIn('issue: "o/r#1"', md)


if __name__ == "__main__":
    unittest.main()
