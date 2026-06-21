"""test_mutation_audit.py — mutation testing determinista: un oráculo fuerte mata los mutantes;
uno débil deja sobrevivientes. Sin LLM. Restaura el target siempre."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import mutation_audit  # noqa: E402

# target con un comparador (>=) -> mutación cmp; un test que distingue el límite lo MATA.
TARGET = "def is_adult(age):\n    return age >= 18\n"


def _fixture(strong=True):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(TARGET, encoding="utf-8")
    if strong:  # prueba el límite exacto (17->False, 18->True): caza >= vs >
        test = ("from impl import is_adult\n"
                "assert is_adult(18) is True\n"
                "assert is_adult(17) is False\n")
    else:  # solo prueba lejos del límite: NO distingue >= de > (mutante sobrevive)
        test = "from impl import is_adult\nassert is_adult(99) is True\n"
    (d / "t.py").write_text(test, encoding="utf-8")
    (d / "c.md").write_text(
        '---\ntask: is-adult\ntarget: impl.py\nsignature: "def is_adult(age)"\n'
        'tests: t.py\ntest_command: "python t.py"\ntest_cwd: "."\n---\n', encoding="utf-8")
    return d, d / "c.md"


class MutationAuditTest(unittest.TestCase):
    def test_strong_oracle_kills_all(self):
        d, c = _fixture(strong=True)
        try:
            res = mutation_audit.audit(c)
            restored = (d / "impl.py").read_text(encoding="utf-8")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertGreater(res["mutants"], 0)
        self.assertTrue(res["ok"], msg=str(res["survived"]))
        self.assertEqual(res["mutation_score"], 1.0)
        self.assertEqual(restored, TARGET)  # target restaurado

    def test_weak_oracle_leaves_survivor(self):
        d, c = _fixture(strong=False)
        try:
            res = mutation_audit.audit(c)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertFalse(res["ok"])
        self.assertTrue(res["survived"])  # el mutante >= -> > sobrevive


    def test_non_python_contract_skipped_not_crash(self):
        # contrato javascript: ast.parse del target .js crashearía -> debe skippear con ok=True
        d = Path(tempfile.mkdtemp())
        try:
            (d / "impl.js").write_text("function f(x){ return x; }\n", encoding="utf-8")
            (d / "t.js").write_text("// test\n", encoding="utf-8")
            (d / "c.md").write_text(
                '---\ntask: f\ntarget: impl.js\nsignature: "function f(x)"\ntests: t.js\n'
                'test_command: "node t.js"\nlanguage: javascript\n---\n', encoding="utf-8")
            res = mutation_audit.audit(d / "c.md")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertTrue(res["ok"])
        self.assertEqual(res["mutants"], 0)


if __name__ == "__main__":
    unittest.main()
