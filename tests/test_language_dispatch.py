"""test_language_dispatch.py — tests CONGELADOS del dispatch por lenguaje (#5). Sin LLM.

Cubre la aceptación de la issue:
  - measure_complexity enruta por language/filename; default python (back-compat).
  - El hook/CLI complexity_gate mide .py igual que antes; extensión sin backend = no-op anunciado (exit 0).
  - complexity_runner resuelve backend por --language/extensión; sin backend = aborto explícito (exit 3).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNERS = REPO / "runners"
sys.path.insert(0, str(RUNNERS))
import metrics_backends as mb       # noqa: E402
import complexity_mcp               # noqa: E402
import complexity_runner            # noqa: E402

GATE = RUNNERS / "complexity_gate.py"

CRIT_PY = """def f(a):
    if a:
        for i in a:
            while i:
                with open(i) as h:
                    if h:
                        return 1
"""


def run_gate(path, *extra):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(GATE), str(path), *extra],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


class FakeBackend(mb.Backend):
    language = "fakelang"
    extensions = (".fk",)
    tool = "fake"
    version = "9"

    def measure(self, src):
        return [{"function": "g", "line": 1, "cyclomatic": 2,
                 "nesting_depth": 1, "parameter_count": 1, "function_length": 3}]


class TestComplexityGateCLI(unittest.TestCase):
    def test_python_critical_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.py"
            p.write_text(CRIT_PY, encoding="utf-8")
            r = run_gate(p)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)

    def test_python_clean_passes(self):
        r = run_gate(REPO / "examples" / "sandbox" / "disassembler.py")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_backend_extension_is_announced_noop(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.cobol"                            # extensión sin backend registrado
            p.write_text("whatever\n", encoding="utf-8")
            r = run_gate(p)
        self.assertEqual(r.returncode, 0, r.stderr)            # no-op, no bloquea
        self.assertIn("sin backend", r.stderr)                 # anunciado, no silencioso

    def test_language_flag_forces_backend(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.cobol"
            p.write_text(CRIT_PY, encoding="utf-8")            # contenido python en archivo .cobol
            r = run_gate(p, "--language", "python")
        self.assertEqual(r.returncode, 2, r.stderr)            # forzado a python -> mide -> CRÍTICA


class TestMeasureComplexityMCP(unittest.TestCase):
    def test_default_python_back_compat(self):
        out = complexity_mcp.measure_complexity({"code": "def f(a, b):\n    return a + b\n"})
        self.assertEqual(out["tool"], "ccdd-ast-metrics")
        self.assertIn("findings", out)

    def test_filename_extension_routes_python(self):
        out = complexity_mcp.measure_complexity({"code": "def f():\n    pass\n", "filename": "m.py"})
        self.assertEqual(out["tool"], "ccdd-ast-metrics")

    def test_language_routes_to_registered_backend(self):
        try:
            mb.register(FakeBackend())
            out = complexity_mcp.measure_complexity({"code": "whatever", "language": "fakelang"})
            self.assertEqual(out["tool"], "fake")
            self.assertEqual(out["version"], "9")
        finally:
            mb._BY_LANG.pop("fakelang", None)
            mb._BY_EXT.pop(".fk", None)

    def test_unknown_language_returns_explicit_error(self):
        out = complexity_mcp.measure_complexity({"code": "x", "language": "klingon"})
        self.assertIn("error", out)
        self.assertIn("python", out["available_languages"])


class TestComplexityRunnerDispatch(unittest.TestCase):
    def test_runner_has_language_flag(self):
        a = complexity_runner.parse_args(["--input", "x.py", "--language", "python"])
        self.assertEqual(a.language, "python")

    def test_build_inputs_python(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.py"
            p.write_text("def f(a):\n    return a\n", encoding="utf-8")
            a = argparse.Namespace(input=str(p), language=None, repo_map=None, debt=None)
            inp, inputs, det = complexity_runner.build_inputs(a)
        self.assertEqual(det["tool"], "ccdd-ast-metrics")
        self.assertIn("lint_results", inputs)

    def test_build_inputs_no_backend_aborts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.cobol"                            # extensión sin backend registrado
            p.write_text("whatever\n", encoding="utf-8")
            a = argparse.Namespace(input=str(p), language=None, repo_map=None, debt=None)
            with self.assertRaises(SystemExit) as cm:
                complexity_runner.build_inputs(a)
        self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
