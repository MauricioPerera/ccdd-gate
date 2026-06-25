"""test_mutdef_check.py — property-tests CONGELADOS de mutable_defaults (runners/mutdef_check.py).
Oráculo independiente: casos fijos. Devuelve la lista ORDENADA de nombres de parámetro cuyo default
es mutable ([]/{}/set()/list()/dict()/...). Vacío = seguro. Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from mutdef_check import mutable_defaults  # noqa: E402


class TestMutableDefaults(unittest.TestCase):
    def test_list_literal(self):
        self.assertEqual(mutable_defaults("def f(x=[]):\n    return x\n", "f"), ["x"])

    def test_dict_literal(self):
        self.assertEqual(mutable_defaults("def f(x={}):\n    return x\n", "f"), ["x"])

    def test_set_call(self):
        self.assertEqual(mutable_defaults("def f(x=set()):\n    return x\n", "f"), ["x"])

    def test_list_call(self):
        self.assertEqual(mutable_defaults("def f(x=list()):\n    return x\n", "f"), ["x"])

    def test_dict_call(self):
        self.assertEqual(mutable_defaults("def f(x=dict()):\n    return x\n", "f"), ["x"])

    def test_immutable_defaults_ok(self):
        self.assertEqual(mutable_defaults("def f(a=0, b='s', c=None, d=()):\n    return a\n", "f"), [])

    def test_only_the_mutable_one(self):
        self.assertEqual(mutable_defaults("def f(x=0, y=[]):\n    return y\n", "f"), ["y"])

    def test_kwonly_default(self):
        self.assertEqual(mutable_defaults("def f(*, k=[]):\n    return k\n", "f"), ["k"])

    def test_kwonly_immutable_ok(self):
        # kw-only con default inmutable -> []. Mata el mutante and->or de la rama kw-only.
        self.assertEqual(mutable_defaults("def f(*, k=0):\n    return k\n", "f"), [])

    def test_multiple_sorted(self):
        self.assertEqual(mutable_defaults("def f(a=[], b={}):\n    return a\n", "f"), ["a", "b"])

    def test_not_found(self):
        self.assertEqual(mutable_defaults("def g(x=[]):\n    return x\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(mutable_defaults("def (bad", "f"), [])

    def test_target_line_disambiguates(self):
        src = "def f(x=[]):\n    return x\n\ndef f(x=0):\n    return x\n"  # f@L1 mutable, f@L4 ok
        self.assertEqual(mutable_defaults(src, "f", target_line=4), [])
        self.assertEqual(mutable_defaults(src, "f", target_line=1), ["x"])


if __name__ == "__main__":
    unittest.main()
