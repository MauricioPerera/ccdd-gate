"""test_treesitter_backend.py — tests del backend tree-sitter TS/JS (#1, decisión #7). Sin LLM.

La dependencia es OPCIONAL: si tree_sitter / la gramática no están instalados, la suite se SALTA
(no falla), reflejando que el camino por defecto (Python) no la necesita.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNERS = REPO / "runners"
sys.path.insert(0, str(RUNNERS))
import metrics_backends as mb  # noqa: E402

_HAS_TS = "typescript" in mb.supported_languages()
skip_no_ts = unittest.skipUnless(_HAS_TS, "tree-sitter (typescript) no instalado: dep opcional")

TS_SAMPLE = """function decode(rom, pc) {
  if (rom && pc) {
    return 1;
  }
  return 2;
}
const arrow = (a, b, c) => a;
class K {
  method(a, b) {
    return a + b;
  }
}
"""


@skip_no_ts
class TestTreeSitterMetrics(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="typescript")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("function f(a) { return a; }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(TS_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(TS_SAMPLE)}
        self.assertIn("decode", names)   # function_declaration
        self.assertIn("arrow", names)    # arrow_function vía variable_declarator
        self.assertIn("method", names)   # method_definition

    def test_arity_with_nested_generics(self):
        m = self.b.measure("function g(a: Map<string, number>, b: number[]) { return b; }")[0]
        self.assertEqual(m["parameter_count"], 2)


@skip_no_ts
class TestRoutingAndConformance(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="typescript").language, "typescript")
        self.assertEqual(mb.get_backend(extension=".ts").language, "typescript")
        self.assertEqual(mb.get_backend(filename="a.js").language, "javascript")

    def test_typescript_registered(self):
        self.assertIn("typescript", mb.supported_languages())
        self.assertIn(".ts", mb.supported_extensions())


@skip_no_ts
class TestGateEndToEndTS(unittest.TestCase):
    def test_gate_blocks_critical_ts(self):
        deep = ("function f(a) {\n  for (const x of a) {\n    if (x) {\n      while (x) {\n"
                "        try {\n          if (x) { return x; }\n        } finally {}\n"
                "      }\n    }\n  }\n}\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.ts"
            p.write_text(deep, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


class TestOptionalDependency(unittest.TestCase):
    """Sin tree-sitter, el sistema sigue: python disponible y get_backend(python) funciona."""

    def test_python_always_available(self):
        self.assertIn("python", mb.supported_languages())
        self.assertEqual(mb.get_backend(language="python").language, "python")


if __name__ == "__main__":
    unittest.main()
