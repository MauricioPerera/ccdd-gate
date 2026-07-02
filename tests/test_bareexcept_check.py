"""test_bareexcept_check.py — property-tests CONGELADOS de bare_except_lines. Oráculo independiente:
casos fijos. Devuelve los números de línea de los `except:` DESNUDOS (sin tipo) en el cuerpo de la
función. Vacío = ninguno. Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from bareexcept_check import bare_except_lines  # noqa: E402


class TestBareExcept(unittest.TestCase):
    def test_bare(self):
        src = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        self.assertEqual(bare_except_lines(src, "f"), [4])

    def test_typed_ok(self):
        src = "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
        self.assertEqual(bare_except_lines(src, "f"), [])

    def test_broad_but_typed_ok(self):
        src = "def f():\n    try:\n        pass\n    except Exception:\n        pass\n"
        self.assertEqual(bare_except_lines(src, "f"), [])

    def test_multiple(self):
        src = ("def f():\n    try:\n        pass\n    except:\n        pass\n"
               "    try:\n        pass\n    except:\n        pass\n")
        self.assertEqual(bare_except_lines(src, "f"), [4, 8])

    def test_not_found(self):
        self.assertEqual(bare_except_lines("def g():\n    try:\n        pass\n    except:\n        pass\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(bare_except_lines("def (bad", "f"), [])

    def test_no_try(self):
        self.assertEqual(bare_except_lines("def f():\n    return 1\n", "f"), [])

    def test_target_line_disambiguates(self):
        src = ("def f():\n    try:\n        pass\n    except:\n        pass\n\n"
               "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n")
        self.assertEqual(bare_except_lines(src, "f", target_line=7), [])
        self.assertEqual(bare_except_lines(src, "f", target_line=1), [4])

    # --- except (): tupla vacía atrapa todo igual que except: (falso negativo: type es Tuple, no None) ---
    def test_empty_tuple_is_bare(self):
        src = "def f():\n    try:\n        pass\n    except ():\n        pass\n"
        self.assertEqual(bare_except_lines(src, "f"), [4])

    def test_nonempty_tuple_not_bare(self):
        src = "def f():\n    try:\n        pass\n    except (ValueError, KeyError):\n        pass\n"
        self.assertEqual(bare_except_lines(src, "f"), [])

    # --- falso positivo por función anidada: el except desnudo de inner NO se atribuye a f ---
    def test_nested_bare_not_attributed(self):
        src = (
            "def f():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        def inner():\n"
            "            try:\n"
            "                pass\n"
            "            except:\n"
            "                pass\n"
            "    return 1\n"
        )
        self.assertEqual(bare_except_lines(src, "f"), [])


if __name__ == "__main__":
    unittest.main()
