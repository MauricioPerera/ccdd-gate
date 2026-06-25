"""test_purity_check.py — property-tests CONGELADOS de impure_operations (runners/purity_check.py).
Oráculo independiente: casos fijos. impure_operations devuelve la lista ORDENADA y SIN duplicados de
las "marcas" de impureza halladas en el cuerpo de la función. Vacío = función pura. Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from purity_check import impure_operations  # noqa: E402


class TestImpureOperations(unittest.TestCase):
    def test_pure(self):
        self.assertEqual(impure_operations("def f(x):\n    return x + 1\n", "f"), [])

    def test_print(self):
        self.assertEqual(impure_operations("def f(x):\n    print(x)\n    return x\n", "f"), ["print"])

    def test_open(self):
        self.assertEqual(impure_operations("def f(x):\n    open('a')\n    return x\n", "f"), ["open"])

    def test_global(self):
        self.assertEqual(impure_operations("def f(x):\n    global G\n    return x\n", "f"), ["global"])

    def test_import_inside(self):
        self.assertEqual(impure_operations("def f(x):\n    import os\n    return os\n", "f"), ["import"])

    def test_eval_exec(self):
        self.assertEqual(impure_operations("def f(x):\n    return eval(x)\n", "f"), ["eval"])

    def test_multiple_sorted_unique(self):
        src = "def f(x):\n    print(x)\n    open('a')\n    print(x)\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["open", "print"])

    def test_non_denylist_call_is_pure(self):
        # len() es una llamada pero NO está en el denylist -> pura. Mata el mutante and->or de L33.
        self.assertEqual(impure_operations("def f(x):\n    return len(x)\n", "f"), [])

    def test_not_found(self):
        self.assertEqual(impure_operations("def g(x):\n    print(x)\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(impure_operations("def (bad", "f"), [])

    def test_target_line_disambiguates(self):
        src = "def f(a):\n    print(a)\n\ndef f(x):\n    return x\n"  # f@L1 impuro, f@L4 puro
        self.assertEqual(impure_operations(src, "f", target_line=4), [])
        self.assertEqual(impure_operations(src, "f", target_line=1), ["print"])


if __name__ == "__main__":
    unittest.main()
