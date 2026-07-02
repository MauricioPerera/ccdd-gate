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

    # --- fábricas mutables extra (falso negativo: sólo {list,dict,set}) ---
    def test_bytearray_call(self):
        self.assertEqual(mutable_defaults("def f(x=bytearray()):\n    return x\n", "f"), ["x"])

    def test_collections_defaultdict_attr(self):
        src = "def f(x=collections.defaultdict()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_collections_deque_attr(self):
        src = "def f(x=collections.deque()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_collections_ordereddict_attr(self):
        src = "def f(x=collections.OrderedDict()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_from_collections_defaultdict_name(self):
        src = "from collections import defaultdict\ndef f(x=defaultdict()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_from_collections_deque_name(self):
        src = "from collections import deque\ndef f(x=deque()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_dict_fromkeys(self):
        src = "def f(x=dict.fromkeys('ab')):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_copy_on_list_literal(self):
        src = "def f(x=[].copy()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_copy_on_dict_literal(self):
        src = "def f(x={}.copy()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_copy_on_mutable_factory(self):
        src = "def f(x=dict().copy()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    def test_copy_on_fromkeys_chain(self):
        src = "def f(x=dict.fromkeys('ab').copy()):\n    return x\n"
        self.assertEqual(mutable_defaults(src, "f"), ["x"])

    # --- frozenset/tuple NO son mutables (no se marcan) ---
    def test_frozenset_not_mutable(self):
        self.assertEqual(mutable_defaults("def f(x=frozenset()):\n    return x\n", "f"), [])

    def test_tuple_not_mutable(self):
        self.assertEqual(mutable_defaults("def f(x=tuple()):\n    return x\n", "f"), [])

    def test_copy_on_immutable_not_flagged(self):
        # frozenset().copy() devuelve frozenset (inmutable) -> no se marca.
        self.assertEqual(mutable_defaults("def f(x=frozenset().copy()):\n    return x\n", "f"), [])


if __name__ == "__main__":
    unittest.main()
