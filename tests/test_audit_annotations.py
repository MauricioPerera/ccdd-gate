"""test_audit_annotations.py — scan project-wide del gate de anotaciones (nombres sin importar).
Determinista, sin LLM."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import audit_annotations  # noqa: E402


def _proj(buggy):
    d = Path(tempfile.mkdtemp())
    body = "def f(x: Node):\n    return x\n" if buggy else "def f(x: int) -> int:\n    return x\n"
    (d / "f.py").write_text(body, encoding="utf-8")
    (d / "f.md").write_text("---\ntask: f\ntarget: f.py\n---\n", encoding="utf-8")
    return d


class AuditAnnotationsTest(unittest.TestCase):
    def test_clean_ok(self):
        d = _proj(buggy=False)
        try:
            res = audit_annotations.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(res["checked"], 1)
        self.assertTrue(res["ok"])

    def test_undefined_annotation_flagged(self):
        d = _proj(buggy=True)
        try:
            res = audit_annotations.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["failures"]), 1)
        self.assertIn("Node", res["failures"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
