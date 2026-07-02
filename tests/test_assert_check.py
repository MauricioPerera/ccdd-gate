"""test_assert_check.py — property-tests CONGELADOS de assert_lines. Oráculo independiente: casos
fijos. Devuelve los números de línea de las sentencias `assert` del cuerpo de la función (footgun:
desaparecen con `python -O`). Vacío = ninguna. Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from assert_check import assert_lines  # noqa: E402


class TestAssertLines(unittest.TestCase):
    def test_single(self):
        self.assertEqual(assert_lines("def f(x):\n    assert x\n    return x\n", "f"), [2])

    def test_none(self):
        self.assertEqual(assert_lines("def f(x):\n    return x\n", "f"), [])

    def test_multiple(self):
        self.assertEqual(assert_lines("def f(x):\n    assert x\n    assert x > 0\n    return x\n", "f"), [2, 3])

    def test_assert_in_nested_block(self):
        self.assertEqual(assert_lines("def f(x):\n    if x:\n        assert x\n    return x\n", "f"), [3])

    def test_not_found(self):
        self.assertEqual(assert_lines("def g(x):\n    assert x\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(assert_lines("def (bad", "f"), [])

    def test_target_line_disambiguates(self):
        src = "def f(x):\n    assert x\n    return x\n\ndef f(x):\n    return x\n"  # f@L1 assert, f@L5 limpio
        self.assertEqual(assert_lines(src, "f", target_line=5), [])
        self.assertEqual(assert_lines(src, "f", target_line=1), [2])

    # --- falso positivo por función anidada: el assert de inner NO se atribuye a f ---
    def test_nested_assert_not_attributed(self):
        src = (
            "def f(x):\n"
            "    def inner(y):\n"
            "        assert y > 0\n"
            "    return x\n"
        )
        self.assertEqual(assert_lines(src, "f"), [])

    def test_assert_in_nested_block_still_attributed(self):
        # bloque anidado (if) NO es función anidada -> sigue contando.
        self.assertEqual(assert_lines("def f(x):\n    if x:\n        assert x\n    return x\n", "f"), [3])


if __name__ == "__main__":
    unittest.main()
