"""test_rules_gate.py — tests CONGELADOS de rules_gate (checks deterministas project-wide por glob).
Sin LLM. Cubre scan_source (por check) y el veredicto del gate sobre archivos reales en un tempdir."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import rules_gate  # noqa: E402


class ScanSource(unittest.TestCase):
    def test_bare_except(self):
        src = "def f():\n    try:\n        pass\n    except:\n        pass\n"
        self.assertEqual(rules_gate.scan_source(src, "bare_except"), [4])

    def test_assert(self):
        self.assertEqual(rules_gate.scan_source("def f(x):\n    assert x\n    return x\n", "assert"), [2])

    def test_none_eq(self):
        self.assertEqual(rules_gate.scan_source("def f(x):\n    return x == None\n", "none_eq"), [2])

    def test_mutable_defaults_uses_def_line(self):
        # check por-función: reporta la línea del def
        self.assertEqual(rules_gate.scan_source("def f(x=[]):\n    return x\n", "mutable_defaults"), [1])

    def test_purity_uses_def_line(self):
        self.assertEqual(rules_gate.scan_source("def f(x):\n    print(x)\n    return x\n", "purity"), [1])

    def test_clean_source(self):
        self.assertEqual(rules_gate.scan_source("def f(x):\n    return x\n", "bare_except"), [])

    def test_unknown_check(self):
        self.assertEqual(rules_gate.scan_source("def f(): pass\n", "nope"), [])

    def test_parse_error(self):
        self.assertEqual(rules_gate.scan_source("def (bad", "assert"), [])

    def test_multiple_functions_deduped_sorted(self):
        src = ("def a():\n    try:\n        pass\n    except:\n        pass\n"
               "def b():\n    try:\n        pass\n    except:\n        pass\n")
        self.assertEqual(rules_gate.scan_source(src, "bare_except"), [4, 9])


class RulesGate(unittest.TestCase):
    def _repo(self, rules_yaml, files):
        d = Path(tempfile.mkdtemp())
        (d / "rules.yaml").write_text(rules_yaml, encoding="utf-8")
        for rel, content in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return d

    def test_fail_on_violation(self):
        d = self._repo(
            "- check: bare_except\n  files: src/**/*.py\n",
            {"src/m.py": "def f():\n    try:\n        pass\n    except:\n        pass\n"})
        try:
            v = rules_gate.gate(str(d / "rules.yaml"), str(d))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["violations"][0]["check"], "bare_except")
            self.assertEqual(v["violations"][0]["lines"], [4])
        finally:
            shutil.rmtree(d)

    def test_pass_when_clean(self):
        d = self._repo(
            "- check: bare_except\n  files: src/**/*.py\n",
            {"src/m.py": "def f():\n    return 1\n"})
        try:
            self.assertEqual(rules_gate.gate(str(d / "rules.yaml"), str(d))["verdict"], "PASS")
        finally:
            shutil.rmtree(d)

    def test_glob_scopes(self):
        # la regla solo mira src/**; un except desnudo fuera de src no cuenta
        d = self._repo(
            "- check: bare_except\n  files: src/**/*.py\n",
            {"src/ok.py": "def f():\n    return 1\n",
             "other/bad.py": "def g():\n    try:\n        pass\n    except:\n        pass\n"})
        try:
            self.assertEqual(rules_gate.gate(str(d / "rules.yaml"), str(d))["verdict"], "PASS")
        finally:
            shutil.rmtree(d)

    def test_invalid_config(self):
        d = self._repo("- files: src/**/*.py\n", {})  # falta 'check'
        try:
            self.assertEqual(rules_gate.gate(str(d / "rules.yaml"), str(d))["verdict"], "INVALID")
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
