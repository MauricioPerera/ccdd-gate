"""test_coverage_check.py — property-tests CONGELADOS de function_lines (runners/coverage_check.py).
Oráculo independiente: casos fijos con el conjunto de líneas esperado calculado a mano. Sin LLM.

function_lines devuelve los números de línea de las SENTENCIAS del CUERPO de la función objetivo
(las que la ejecución de los tests debería cubrir), excluyendo la línea del `def`/decoradores."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from coverage_check import function_lines  # noqa: E402


class TestFunctionLines(unittest.TestCase):
    def test_flat_body(self):
        # L1 def, L2 a=1, L3 return -> cuerpo {2,3}
        self.assertEqual(function_lines("def f(x):\n    a = 1\n    return a\n", "f"), {2, 3})

    def test_branch_body(self):
        # L1 def, L2 if, L3 return 1, L4 return 0 -> {2,3,4}
        self.assertEqual(function_lines("def f(x):\n    if x:\n        return 1\n    return 0\n", "f"), {2, 3, 4})

    def test_excludes_def_line(self):
        self.assertNotIn(1, function_lines("def f(x):\n    return x\n", "f"))

    def test_async_function(self):
        self.assertEqual(function_lines("async def f(x):\n    return x\n", "f"), {2})

    def test_function_not_found(self):
        self.assertEqual(function_lines("def g(x):\n    return x\n", "f"), set())

    def test_parse_error(self):
        self.assertEqual(function_lines("def (bad", "f"), set())

    def test_target_line_disambiguates(self):
        # f@L1 (cuerpo L2) y f@L4 (cuerpo L5); target_line=4 -> {5}
        src = "def f(a):\n    return a\n\ndef f(x):\n    return x\n"
        self.assertEqual(function_lines(src, "f", target_line=4), {5})

    def test_target_line_first_def(self):
        src = "def f(a):\n    return a\n\ndef f(x):\n    return x\n"
        self.assertEqual(function_lines(src, "f", target_line=1), {2})


if __name__ == "__main__":
    unittest.main()
