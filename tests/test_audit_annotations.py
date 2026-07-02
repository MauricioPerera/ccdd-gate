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


class AuditStringForwardRefTest(unittest.TestCase):
    """Forward-refs en string (`x: "UndefinedNode"`, `-> "Missing"`, `List["Node"]`) son
    `ast.Constant[str]`; el gate las parsea y reporta nombres sin importar/definir — el bug que
    rompe en runtime <Py3.14."""

    def test_undefined_string_forward_ref_flagged(self):
        d = Path(tempfile.mkdtemp())
        (d / "f.py").write_text('def f(x: "UndefinedNode") -> "Missing":\n    return x\n',
                                encoding="utf-8")
        (d / "f.md").write_text("---\ntask: f\ntarget: f.py\n---\n", encoding="utf-8")
        try:
            res = audit_annotations.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"], msg=str(res["failures"]))
        detail = res["failures"][0]["detail"]
        self.assertIn("UndefinedNode", detail)
        self.assertIn("Missing", detail)

    def test_defined_string_forward_ref_ok(self):
        d = Path(tempfile.mkdtemp())
        (d / "f.py").write_text(
            "from m import Node\n\n\ndef f(x: \"Node\") -> \"Node\":\n    return x\n",
            encoding="utf-8")
        (d / "f.md").write_text("---\ntask: f\ntarget: f.py\n---\n", encoding="utf-8")
        try:
            res = audit_annotations.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(res["ok"], msg=str(res["failures"]))

    def test_undefined_nested_string_forward_ref_flagged(self):
        # List["UndefinedNode"]: la string vive dentro de un sub-nodo de la anotación
        d = Path(tempfile.mkdtemp())
        (d / "f.py").write_text(
            "from typing import List\n\n\ndef f(x: List[\"UndefinedNode\"]):\n    return x\n",
            encoding="utf-8")
        (d / "f.md").write_text("---\ntask: f\ntarget: f.py\n---\n", encoding="utf-8")
        try:
            res = audit_annotations.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"], msg=str(res["failures"]))
        self.assertIn("UndefinedNode", res["failures"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
