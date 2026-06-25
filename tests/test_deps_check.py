"""test_deps_check.py — tests unitarios de unauthorized_imports (runners/deps_check.py). Oráculo
independiente: casos fijos con salida esperada calculada a mano. Sin LLM, deterministas."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from deps_check import unauthorized_imports  # noqa: E402


class TestUnauthorizedImports(unittest.TestCase):
    def test_thirdparty_flagged(self):
        self.assertEqual(unauthorized_imports("import os\nimport requests", []), ["requests"])

    def test_stdlib_ignored(self):
        self.assertEqual(unauthorized_imports("import os\nimport sys\nimport json", []), [])

    def test_allowed_ignored(self):
        self.assertEqual(unauthorized_imports("import requests", ["requests"]), [])

    def test_from_import_stdlib(self):
        self.assertEqual(unauthorized_imports("from collections import OrderedDict", []), [])

    def test_from_import_thirdparty(self):
        self.assertEqual(unauthorized_imports("from flask import Flask", []), ["flask"])

    def test_relative_ignored(self):
        self.assertEqual(unauthorized_imports("from . import helper\nfrom .sub import x", []), [])

    def test_dotted_toplevel(self):
        self.assertEqual(unauthorized_imports("import a.b.c", []), ["a"])

    def test_sorted_and_unique(self):
        self.assertEqual(unauthorized_imports("import zebra\nimport apple\nimport zebra", []), ["apple", "zebra"])

    def test_future_ignored(self):
        self.assertEqual(unauthorized_imports("from __future__ import annotations", []), [])

    def test_syntax_error_returns_empty(self):
        self.assertEqual(unauthorized_imports("import (", []), [])

    def test_mixed(self):
        src = "import os\nimport numpy as np\nfrom flask import Flask\nfrom . import local"
        self.assertEqual(unauthorized_imports(src, ["numpy"]), ["flask"])


if __name__ == "__main__":
    unittest.main()
