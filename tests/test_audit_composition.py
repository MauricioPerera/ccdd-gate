"""test_audit_composition.py — el auditor destaca composición sin gatear y la silencia cuando un
grupo la cubre. Determinista, sin LLM."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import audit_composition  # noqa: E402


def _fixture(grouped=False):
    """a.py importa b.py; ambos son targets de contratos de función. Con grouped=True, un
    contrato kind:group cubre a a.md y b.md."""
    d = Path(tempfile.mkdtemp())
    (d / "a.py").write_text("from b import g\n\n\ndef f():\n    return g()\n", encoding="utf-8")
    (d / "b.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    (d / "a.md").write_text("---\ntask: a\ntarget: a.py\n---\n", encoding="utf-8")
    (d / "b.md").write_text("---\ntask: b\ntarget: b.py\n---\n", encoding="utf-8")
    if grouped:
        (d / "grp.md").write_text(
            "---\nkind: group\ntask: grp\nchildren:\n  - a.md\n  - b.md\n"
            'integration_test_command: "python -m pytest t.py"\n---\n', encoding="utf-8")
    return d


class AuditCompositionTest(unittest.TestCase):
    def test_flags_ungated_composition(self):
        d = _fixture(grouped=False)
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"])
        self.assertEqual(res["functions"], 2)
        flagged = {Path(u["contract"]).name for u in res["ungated_composition"]}
        self.assertIn("a.md", flagged)   # a importa b y no está en grupo
        self.assertNotIn("b.md", flagged)  # b no compone a nadie

    def test_group_silences_it(self):
        d = _fixture(grouped=True)
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(res["ok"], msg=str(res["ungated_composition"]))
        self.assertEqual(res["groups"], 1)


if __name__ == "__main__":
    unittest.main()
