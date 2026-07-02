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


class CompositionBehaviorTest(unittest.TestCase):
    """Refinamiento: una composición cuyo test del composer EJERCITA los hijos reales (sin mock) es
    deuda de FORMA (ok=True). Si el test MOCKEA, es deuda de COMPORTAMIENTO (ok=False)."""

    def _proj(self, test_body):
        d = Path(tempfile.mkdtemp())
        (d / "b.py").write_text("def b():\n    return 1\n", encoding="utf-8")
        (d / "a.py").write_text("from b import b\n\n\ndef a():\n    return b()\n", encoding="utf-8")
        (d / "test_b.py").write_text("from b import b\nassert b() == 1\n", encoding="utf-8")
        (d / "test_a.py").write_text(test_body, encoding="utf-8")
        (d / "b.md").write_text("---\ntask: b\ntarget: b.py\ntests: test_b.py\n---\n", encoding="utf-8")
        (d / "a.md").write_text("---\ntask: a\ntarget: a.py\ntests: test_a.py\n---\n", encoding="utf-8")
        return d

    def test_exercised_composition_is_form_debt(self):
        # test_a ejercita la composición real (sin mock) -> deuda de forma, ok=True
        d = self._proj("from a import a\nassert a() == 1\n")
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(res["ok"], msg=str(res["behavior_unverified"]))
        self.assertEqual(len(res["ungated_composition"]), 1)   # sigue siendo deuda de forma
        self.assertEqual(res["behavior_unverified"], [])

    def test_mocked_composition_is_behavior_debt(self):
        d = self._proj("from unittest.mock import patch\nfrom a import a\nassert a() == 1\n")
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"])
        self.assertEqual(len(res["behavior_unverified"]), 1)


class CompositionSymbolVsModuleTest(unittest.TestCase):
    """`from pkg.helper import util` importa el SÍMBOLO util, no el módulo util.py: NO debe marcar
    composición falsa. El stem del módulo de origen (helper) sí cuenta; el nombre del símbolo no."""

    def test_symbol_import_not_flagged_as_module_composition(self):
        d = Path(tempfile.mkdtemp())
        (d / "pkg").mkdir()
        (d / "pkg" / "helper.py").write_text("def util():\n    return 1\n", encoding="utf-8")
        (d / "main.py").write_text("from pkg.helper import util\n\n\ndef main():\n    return util()\n",
                                   encoding="utf-8")
        (d / "util.py").write_text("def util():\n    return 2\n", encoding="utf-8")
        (d / "main.md").write_text("---\ntask: main\ntarget: main.py\n---\n", encoding="utf-8")
        (d / "util.md").write_text("---\ntask: util\ntarget: util.py\n---\n", encoding="utf-8")
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        flagged = {Path(u["contract"]).name for u in res["ungated_composition"]}
        self.assertNotIn("main.md", flagged)   # importa el símbolo util, no el módulo util.py


class CompositionHomonymCollisionTest(unittest.TestCase):
    """Dos targets con el mismo stem en distinto directorio (aacs/schema.py, b/schema.py) NO se
    pierden por colisión de stem: ambos se rastrean y ambos se reportan si componen."""

    def _proj(self):
        d = Path(tempfile.mkdtemp())
        (d / "aacs").mkdir()
        (d / "b").mkdir()
        body = "from util import u\n\n\ndef schema():\n    return u()\n"
        (d / "aacs" / "schema.py").write_text(body, encoding="utf-8")
        (d / "b" / "schema.py").write_text(body, encoding="utf-8")
        (d / "util.py").write_text("def u():\n    return 1\n", encoding="utf-8")
        (d / "aacs" / "schema.md").write_text("---\ntask: schema\ntarget: schema.py\n---\n", encoding="utf-8")
        (d / "b" / "schema2.md").write_text("---\ntask: schema2\ntarget: schema.py\n---\n", encoding="utf-8")
        (d / "util.md").write_text("---\ntask: util\ntarget: util.py\n---\n", encoding="utf-8")
        return d

    def test_homonyms_not_lost_by_stem_collision(self):
        d = self._proj()
        try:
            res = audit_composition.audit(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(res["functions"], 3)   # antes colisionaban a 2 (last-wins por stem)
        self.assertEqual(len(res["ungated_composition"]), 2)  # ambos homónimos componen util
        flagged = {Path(u["contract"]).name for u in res["ungated_composition"]}
        self.assertIn("schema.md", flagged)      # aacs/schema compone util
        self.assertIn("schema2.md", flagged)     # b/schema compone util (no se perdió)


if __name__ == "__main__":
    unittest.main()
