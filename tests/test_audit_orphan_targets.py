"""test_audit_orphan_targets.py — destaca .py de implementación sin contrato (código fuera del
flujo gate). Determinista, sin LLM."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import audit_orphan_targets  # noqa: E402


def _fixture(orphan=False):
    """f.py es target de f.md. Con orphan=True, agrega g.py SIN contrato (fuera del flujo)."""
    d = Path(tempfile.mkdtemp())
    (d / "f.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (d / "f.md").write_text("---\ntask: f\ntarget: f.py\n---\n", encoding="utf-8")
    (d / "__init__.py").write_text("", encoding="utf-8")           # excluido
    (d / "conftest.py").write_text("import sys\n", encoding="utf-8")  # excluido
    (d / "test_f.py").write_text("def test_f():\n    assert 1\n", encoding="utf-8")  # excluido
    if orphan:
        (d / "g.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    return d


class AuditOrphanTest(unittest.TestCase):
    def test_clean_project_ok(self):
        d = _fixture(orphan=False)
        try:
            res = audit_orphan_targets.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(res["ok"], msg=str(res["orphans"]))
        self.assertEqual(res["contracts"], 1)

    def test_code_without_contract_flagged(self):
        d = _fixture(orphan=True)
        try:
            res = audit_orphan_targets.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"])
        self.assertIn("g.py", res["orphans"])
        self.assertNotIn("f.py", res["orphans"])          # f.py SÍ tiene contrato
        self.assertNotIn("__init__.py", res["orphans"])   # excluido
        self.assertNotIn("test_f.py", res["orphans"])     # excluido


class PureDataExemptionTest(unittest.TestCase):
    """Refinamiento: un .py de datos puros (dataclass sin funciones) NO es 'código sin contrato' —
    no tiene lógica que gatear, así que no se reporta como huérfano."""

    def test_pure_dataclass_not_flagged(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "model.py").write_text(
                "from dataclasses import dataclass\n\n\n@dataclass\nclass N:\n    x: int = 0\n",
                encoding="utf-8")           # sin contrato, pero data pura
            (d / "logic.py").write_text("def f():\n    return 1\n", encoding="utf-8")  # sin contrato, con lógica
            res = audit_orphan_targets.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertNotIn("model.py", res["orphans"])  # data pura: exenta
        self.assertIn("logic.py", res["orphans"])      # lógica sin contrato: huérfano

    def test_toplevel_logic_without_def_not_exempt(self):
        # sin 'def' pero con lógica ejecutable a nivel módulo: NO es data pura -> huérfano
        d = Path(tempfile.mkdtemp())
        try:
            (d / "side.py").write_text("import os\nfor k in os.environ:\n    print(k)\n", encoding="utf-8")
            res = audit_orphan_targets.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIn("side.py", res["orphans"])


if __name__ == "__main__":
    unittest.main()
