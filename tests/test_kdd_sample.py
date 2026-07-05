"""test_kdd_sample.py — property-tests CONGELADOS del contrato kdd-sample-slugify.

Oráculo independiente de la implementación: asserts sobre la FORMA del slug
(solo [a-z0-9-], sin dobles '-', sin '-' en extremos), no sobre el algoritmo.
Cubre los Examples del contrato más los bordes (vacío, solo símbolos, unicode).
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.kdd_sample.slugify import slugify  # noqa: E402


class TestSlugifyExamples(unittest.TestCase):
    """Los Examples del contrato, congelados."""

    def test_hello_world(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")

    def test_repeated_separators_collapse(self):
        self.assertEqual(slugify("Foo--Bar  Baz"), "foo-bar-baz")

    def test_surrounding_whitespace(self):
        self.assertEqual(slugify("  Hola   Mundo  "), "hola-mundo")


class TestSlugifyEdges(unittest.TestCase):
    """Bordes declarados en el contrato: vacío, solo símbolos, unicode."""

    def test_empty_string(self):
        self.assertEqual(slugify(""), "")

    def test_only_symbols(self):
        self.assertEqual(slugify("!!!"), "")

    def test_only_symbols_mixed(self):
        self.assertEqual(slugify("  --  __  "), "")

    def test_unicode_collapses_to_dash(self):
        # 'ú' (no-ASCII) colapsa a '-' según el contrato.
        self.assertEqual(slugify("múltiple"), "m-ltiple")

    def test_keeps_ascii_digits(self):
        self.assertEqual(slugify("Item 42!"), "item-42")


class TestSlugifyInvariants(unittest.TestCase):
    """Invariants del contrato, sobre inputs arbitrarios."""

    def test_only_allowed_chars(self):
        for s in ["Hello World!", "Foo--Bar  Baz", "  Hola   Mundo  ",
                  "!!!", "múltiple", "Item 42!"]:
            out = slugify(s)
            self.assertTrue(all(c.isalnum() and c.isascii() or c == "-" for c in out),
                            f"carácter no permitido en {out!r} (input {s!r})")

    def test_no_double_dash(self):
        for s in ["Foo--Bar  Baz", "  Hola   Mundo  ", "a---b", "x  -  y"]:
            self.assertNotIn("--", slugify(s), f"doble '-' en {slugify(s)!r} (input {s!r})")

    def test_no_edge_dashes(self):
        for s in ["  Hola   Mundo  ", "--foo--", "!!!hola!!!"]:
            out = slugify(s)
            self.assertFalse(out.startswith("-"), f"leading '-' en {out!r}")
            self.assertFalse(out.endswith("-"), f"trailing '-' en {out!r}")


if __name__ == "__main__":
    unittest.main()