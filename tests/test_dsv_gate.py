import json
from pathlib import Path
import tempfile
import unittest

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import ccdd  # noqa: E402


class TestDSVGate(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.src = self.d / "target.py"
        self.src.write_text("def hello():\n    return 'world'\n# Límite 5MB\n", encoding="utf-8")
        
        self.contract_dir = self.d

    def _run_dsv(self, findings):
        g = {
            "id": "test-dsv",
            "type": "dsv_check",
            "target_slot": "vulnerability_report",
            "on_fail": "abort"
        }
        assembled = {"vulnerability_report": json.dumps(findings)}
        ok, detail = ccdd._check_dsv(g, assembled, self.contract_dir)
        return ok, detail

    def test_dsv_exact_match(self):
        findings = [{"file": "target.py", "line": 2, "snippet": "return 'world'"}]
        ok, detail = self._run_dsv(findings)
        self.assertTrue(ok, detail)
        
    def test_dsv_substring_match(self):
        # Even if they only capture part of the line, it should pass
        findings = [{"file": "target.py", "line": 3, "snippet": "5MB"}]
        ok, detail = self._run_dsv(findings)
        self.assertTrue(ok, detail)

    def test_dsv_hallucination_drift(self):
        # Hallucinated content on a real line
        findings = [{"file": "target.py", "line": 2, "snippet": "return 'hello'"}]
        ok, detail = self._run_dsv(findings)
        self.assertFalse(ok)
        self.assertIn("drift detectado", detail)

    def test_dsv_line_out_of_bounds(self):
        findings = [{"file": "target.py", "line": 99, "snippet": "def"}]
        ok, detail = self._run_dsv(findings)
        self.assertFalse(ok)
        self.assertIn("fuera de rango", detail)

    def test_dsv_file_not_found(self):
        findings = [{"file": "ghost.py", "line": 1, "snippet": "def"}]
        ok, detail = self._run_dsv(findings)
        self.assertFalse(ok)
        self.assertIn("archivo no existe", detail)
        
    def test_dsv_invalid_json(self):
        g = {"target_slot": "vulnerability_report"}
        assembled = {"vulnerability_report": "not valid json"}
        ok, detail = ccdd._check_dsv(g, assembled, self.contract_dir)
        self.assertFalse(ok)
        self.assertIn("no es JSON válido", detail)

    def test_dsv_invalid_format(self):
        g = {"target_slot": "vulnerability_report"}
        assembled = {"vulnerability_report": '{"file": "target.py"}'} # dict instead of list
        ok, detail = ccdd._check_dsv(g, assembled, self.contract_dir)
        self.assertFalse(ok)
        self.assertIn("debe ser una lista JSON", detail)

if __name__ == '__main__':
    unittest.main()
