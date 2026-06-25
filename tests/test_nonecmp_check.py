"""test_nonecmp_check.py — property-tests CONGELADOS de none_eq_lines. Oráculo independiente: casos
fijos. Devuelve las líneas donde se compara con None usando ==/!= (en vez de is/is not). Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from nonecmp_check import none_eq_lines  # noqa: E402


class TestNoneEqLines(unittest.TestCase):
    def test_eq_none(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return x == None\n", "f"), [2])

    def test_neq_none(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return x != None\n", "f"), [2])

    def test_is_none_ok(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return x is None\n", "f"), [])

    def test_is_not_none_ok(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return x is not None\n", "f"), [])

    def test_eq_non_none_ok(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return x == 1\n", "f"), [])

    def test_none_on_left(self):
        self.assertEqual(none_eq_lines("def f(x):\n    return None == x\n", "f"), [2])

    def test_nested(self):
        self.assertEqual(none_eq_lines("def f(x):\n    if x != None:\n        return 1\n    return 0\n", "f"), [2])

    def test_not_found(self):
        self.assertEqual(none_eq_lines("def g(x):\n    return x == None\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(none_eq_lines("def (bad", "f"), [])

    def test_target_line_disambiguates(self):
        src = "def f(x):\n    return x == None\n\ndef f(x):\n    return x is None\n"  # f@L1 malo, f@L4 ok
        self.assertEqual(none_eq_lines(src, "f", target_line=4), [])
        self.assertEqual(none_eq_lines(src, "f", target_line=1), [2])


if __name__ == "__main__":
    unittest.main()
