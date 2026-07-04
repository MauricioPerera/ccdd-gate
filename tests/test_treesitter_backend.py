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
_HAS_RUST = "rust" in mb.supported_languages()
skip_no_rust = unittest.skipUnless(_HAS_RUST, "tree-sitter (rust) no instalado: dep opcional")
_HAS_GO = "go" in mb.supported_languages()
skip_no_go = unittest.skipUnless(_HAS_GO, "tree-sitter (go) no instalado: dep opcional")

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


# ── Rust ───────────────────────────────────────────────────────────────────────────────
RUST_SAMPLE = """fn decode(rom: &[u8], pc: usize) -> u8 {
  if !rom.is_empty() && pc > 0 {
    return 1;
  }
  2
}
struct S;
impl S {
  fn method(&self, a: u8, b: u8) -> u8 { a + b }
}
fn with_closure() {
  let f = |a, b| a + b;
  let _ = f(1, 2);
}
"""


@skip_no_rust
class TestTreeSitterRust(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="rust")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("fn f(a: i32) -> i32 { a }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("fn simple(x: i32) -> i32 { x + 1 }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(RUST_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("fn d(items: &[i32]) -> i32 {\n  for a in items {\n    if a {\n"
               "      while a {\n        unsafe {\n          if a { return a; }\n        }\n      }\n    }\n  }\n  0\n}\n")
        m = self.b.measure(src)[0]
        # for + if + while + if = 4 decisiones -> cyc 5; 5 niveles de anidamiento
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(RUST_SAMPLE)}
        self.assertIn("decode", names)        # function_item (fn libre)
        self.assertIn("method", names)        # function_item (método dentro de impl)
        self.assertIn("with_closure", names)  # function_item contenedor
        self.assertIn("f", names)             # closure_expression vía let_declaration

    def test_method_and_closure_params(self):
        fns = {f["function"]: f for f in self.b.measure(RUST_SAMPLE)}
        # &self + a + b = 3 (self_parameter cuenta, espejo del self explícito de Python)
        self.assertEqual(fns["method"]["parameter_count"], 3)
        # closure |a, b| -> 2
        self.assertEqual(fns["f"]["parameter_count"], 2)

    def test_match_counting(self):
        src = "fn s(x: i32) -> i32 { match x { 0 => 0, 1 => 1, 2 => 2, _ => 3 } }"
        m = self.b.measure(src)[0]
        # 4 brazos (match_arm) -> +4 -> cyc 5; match NO anida -> nesting 0
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_rust
class TestRoutingRust(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="rust").language, "rust")
        self.assertEqual(mb.get_backend(extension=".rs").language, "rust")
        self.assertEqual(mb.get_backend(filename="a.rs").language, "rust")

    def test_rust_registered(self):
        self.assertIn("rust", mb.supported_languages())
        self.assertIn(".rs", mb.supported_extensions())


@skip_no_rust
class TestGateEndToEndRust(unittest.TestCase):
    def test_gate_blocks_critical_rust(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "rust" / "deep_nesting.rs")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.rs"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── Go ────────────────────────────────────────────────────────────────────────────────
GO_SAMPLE = """package main

func decode(rom []byte, pc int) int {
  if len(rom) > 0 && pc > 0 {
    return 1
  }
  return 2
}
type S struct{}
func (s S) method(a int, b int) int { return a + b }
func with_funclit() {
  f := func(a int, b int) int { return a + b }
  _ = f(1, 2)
}
"""


@skip_no_go
class TestTreeSitterGo(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="go")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("package main\nfunc f(a int) int { return a }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("package main\nfunc simple(x int) int { return x + 1 }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(GO_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("package main\nfunc d(items []int) int {\n  for _, a := range items {\n"
               "    if a {\n      for a {\n        select {\n        default:\n"
               "          if a { return a }\n        }\n      }\n    }\n  }\n  return 0\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for + if + for + if = 4 decisiones -> cyc 5; select{default:} es nido sin decisión
        # -> 5 niveles (for>if>for>select>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(GO_SAMPLE)}
        self.assertIn("decode", names)        # function_declaration
        self.assertIn("method", names)        # method_declaration (field_identifier)
        self.assertIn("with_funclit", names)  # function_declaration contenedor
        self.assertIn("f", names)             # func_literal vía short_var_declaration

    def test_method_and_funclit_params(self):
        fns = {f["function"]: f for f in self.b.measure(GO_SAMPLE)}
        # receiver `s` NO cuenta (campo "receiver", no "parameters"); a, b = 2
        self.assertEqual(fns["method"]["parameter_count"], 2)
        # func literal (a int, b int) -> 2
        self.assertEqual(fns["f"]["parameter_count"], 2)

    def test_switch_counting(self):
        src = ("package main\nfunc s(x int) int {\n  switch x {\n  case 0: return 0\n"
               "  case 1: return 1\n  case 2: return 2\n  case 3: return 3\n  }\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 expression_case -> +4 -> cyc 5; switch NO anida -> nesting 0
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)

    def test_grouped_params_counted_by_name(self):
        # Go agrupa parámetros que comparten tipo en un solo parameter_declaration con
        # varios identifier hijos. El gate de aridad (params <= 5) exige contar por NOMBRE,
        # no por declaración: `func f(a, b, c, d, e, f int)` son 6 parámetros, no 1.
        src = ("package main\n"
               "func two(a, b int) int { return a + b }\n"
               "func six(a, b, c, d, e, f int) int { return a }\n"
               "func mixed(a, b, c int, d string) int { return a }\n"
               "func variadic(xs ...int) int { return xs }\n")
        fns = {f["function"]: f for f in self.b.measure(src)}
        self.assertEqual(fns["two"]["parameter_count"], 2)
        self.assertEqual(fns["six"]["parameter_count"], 6)
        self.assertEqual(fns["mixed"]["parameter_count"], 4)
        self.assertEqual(fns["variadic"]["parameter_count"], 1)


@skip_no_go
class TestRoutingGo(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="go").language, "go")
        self.assertEqual(mb.get_backend(extension=".go").language, "go")
        self.assertEqual(mb.get_backend(filename="a.go").language, "go")

    def test_go_registered(self):
        self.assertIn("go", mb.supported_languages())
        self.assertIn(".go", mb.supported_extensions())


@skip_no_go
class TestGateEndToEndGo(unittest.TestCase):
    def test_gate_blocks_critical_go(self):
        deep = (REPO / "fixtures" / "conformance" / "go" / "deep_nesting.go")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.go"
            p.write_text(src, encoding="utf-8")
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
