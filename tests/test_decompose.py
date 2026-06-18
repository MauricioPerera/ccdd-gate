"""test_decompose.py — tests CONGELADOS de la descomposición en sub-issues (#15). Sin LLM. Sin red.

Aceptación de la issue:
  - cada contrato atómico produce un sub-issue enlazado (cuerpo resumido + marker).
  - idempotente: re-ejecutar no duplica (detecta por marker del task).
  - vínculo inverso: el campo `issue` del contrato apunta al sub-issue (set_issue_field).
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO / "integrations" / "github"))
import decompose  # noqa: E402

CONTRACT = '---\ntask: chunk-list\nintent: "Partir una lista en sublistas."\nspec_version: "0.1"\n---\n# body\n'


def _contract(text=CONTRACT, name="a.md"):
    d = Path(tempfile.mkdtemp())
    p = d / name
    p.write_text(text, encoding="utf-8")
    return d, p


class TestBuildSubissue(unittest.TestCase):
    def test_title_and_marker(self):
        d, p = _contract()
        try:
            sub = decompose.build_subissue(p)
            self.assertEqual(sub["slug"], "chunk-list")
            self.assertIn("chunk-list", sub["title"])
            self.assertIn("Partir una lista", sub["title"])
            self.assertIn(decompose.task_marker("chunk-list"), sub["body"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestIdempotentPlan(unittest.TestCase):
    def test_create_when_absent(self):
        d, p = _contract()
        try:
            planned = decompose.plan([p], [])
            self.assertEqual(planned[0]["action"], "create")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_skip_when_marker_exists(self):
        d, p = _contract()
        try:
            existing = [{"number": 42, "body": "pre " + decompose.task_marker("chunk-list")}]
            planned = decompose.plan([p], existing)
            self.assertEqual(planned[0]["action"], "skip")
            self.assertEqual(planned[0]["existing_number"], 42)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_find_existing_none(self):
        self.assertIsNone(decompose.find_existing([{"number": 1, "body": "nada"}], "chunk-list"))


class TestSetIssueField(unittest.TestCase):
    def test_inserts_when_absent(self):
        out = decompose.set_issue_field(CONTRACT, "o/r#42")
        self.assertIn('issue: "o/r#42"', out)
        self.assertEqual(out.count("issue:"), 1)

    def test_replaces_once_when_present(self):
        once = decompose.set_issue_field(CONTRACT, "o/r#42")
        twice = decompose.set_issue_field(once, "o/r#99")
        self.assertEqual(twice.count("issue:"), 1)
        self.assertIn("o/r#99", twice)
        self.assertNotIn("o/r#42", twice)

    def test_no_frontmatter_untouched(self):
        self.assertEqual(decompose.set_issue_field("no fm here", "o/r#1"), "no fm here")


class TestDryRunExecute(unittest.TestCase):
    def test_dry_run_does_not_mutate_contract(self):
        d, p = _contract()
        try:
            before = p.read_text(encoding="utf-8")
            planned = decompose.plan([p], [])
            decompose.execute("o/r#9", planned, post=False)
            self.assertEqual(p.read_text(encoding="utf-8"), before)  # dry-run no escribe
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
