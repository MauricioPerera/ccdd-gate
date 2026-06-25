"""test_sig_check.py — property-tests CONGELADOS de signature_mismatch (runners/sig_check.py).
Oráculo independiente: casos fijos. Las coincidencias devuelven "" (cadena vacía); los desajustes
devuelven una cadena NO vacía (el mensaje exacto es libre para el implementador). Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from sig_check import signature_mismatch  # noqa: E402


class TestSignatureMismatch(unittest.TestCase):
    # --- coincidencias: devuelven "" ---
    def test_exact_match(self):
        self.assertEqual(signature_mismatch("def f(x, y): return x", "f", "def f(x, y)"), "")

    def test_annotations_ignored(self):
        self.assertEqual(signature_mismatch("def f(x: int, y: str) -> bool:\n    return True", "f", "def f(x, y)"), "")

    def test_defaults_ignored(self):
        self.assertEqual(signature_mismatch("def f(x, y=3): return x", "f", "def f(x, y)"), "")

    def test_method_self(self):
        self.assertEqual(signature_mismatch("class C:\n    def m(self, a): return a", "m", "def m(self, a)"), "")

    # --- desajustes: devuelven una cadena NO vacía (truthy str; assertTrue descarta None y "") ---
    def test_param_count_differs(self):
        self.assertTrue(signature_mismatch("def f(x): return x", "f", "def f(x, y)"))

    def test_param_name_differs(self):
        self.assertTrue(signature_mismatch("def f(a): return a", "f", "def f(x)"))

    def test_param_order_differs(self):
        self.assertTrue(signature_mismatch("def f(y, x): return x", "f", "def f(x, y)"))

    def test_function_not_found(self):
        self.assertTrue(signature_mismatch("def g(x): return x", "f", "def f(x)"))

    def test_extra_vararg(self):
        self.assertTrue(signature_mismatch("def f(x, *args): return x", "f", "def f(x)"))

    def test_missing_kwarg(self):
        self.assertTrue(signature_mismatch("def f(x): return x", "f", "def f(x, **kw)"))

    def test_returns_str_type(self):
        # el contrato promete -> str: un mutante que devuelva None en un desajuste muere aquí.
        self.assertIsInstance(signature_mismatch("def f(a): return a", "f", "def f(x)"), str)
        self.assertIsInstance(signature_mismatch("def f(x): return x", "f", "def f(x)"), str)

    def test_parse_error_returns_truthy_str(self):
        # source / firma esperada no parseable -> cadena NO vacía (mata el mutante de esa rama).
        self.assertTrue(signature_mismatch("def (bad", "f", "def f(x)"))
        self.assertTrue(signature_mismatch("def f(x): pass", "f", "not a signature"))

    def test_function_name_differs(self):
        # impl 'f' encontrada, pero la firma esperada nombra 'g' -> desajuste de nombre.
        self.assertTrue(signature_mismatch("def f(x): return x", "f", "def g(x)"))

    # --- desambiguación por target_line (funciones homónimas) ---
    _HOMONYMS = "def f(a):\n    return a\n\ndef f(x):\n    return x\n"  # f@L1 (a), f@L4 (x)

    def test_target_line_selects_matching_def(self):
        self.assertEqual(signature_mismatch(self._HOMONYMS, "f", "def f(x)", target_line=4), "")

    def test_target_line_selects_mismatching_def(self):
        self.assertTrue(signature_mismatch(self._HOMONYMS, "f", "def f(x)", target_line=1))


if __name__ == "__main__":
    unittest.main()
