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
_HAS_JAVA = "java" in mb.supported_languages()
skip_no_java = unittest.skipUnless(_HAS_JAVA, "tree-sitter (java) no instalado: dep opcional")
_HAS_CSHARP = "csharp" in mb.supported_languages()
skip_no_csharp = unittest.skipUnless(_HAS_CSHARP, "tree-sitter (c_sharp) no instalado: dep opcional")
_HAS_PHP = "php" in mb.supported_languages()
skip_no_php = unittest.skipUnless(_HAS_PHP, "tree-sitter (php) no instalado: dep opcional")
_HAS_RUBY = "ruby" in mb.supported_languages()
skip_no_ruby = unittest.skipUnless(_HAS_RUBY, "tree-sitter (ruby) no instalado: dep opcional")
_HAS_KOTLIN = "kotlin" in mb.supported_languages()
skip_no_kotlin = unittest.skipUnless(_HAS_KOTLIN, "tree-sitter (kotlin) no instalado: dep opcional")
_HAS_C = "c" in mb.supported_languages()
skip_no_c = unittest.skipUnless(_HAS_C, "tree-sitter (c) no instalado: dep opcional")

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


# ── Java ───────────────────────────────────────────────────────────────────────────────
JAVA_SAMPLE = """public class Sample {
  public Sample(int a) { this.a = a; }
  public static int decode(int[] rom, int pc) {
    if (rom != null && pc > 0) { return 1; }
    return 2;
  }
  private void m(int a, int b) {
    Runnable r = () -> { System.out.println(a); };
  }
}
"""


@skip_no_java
class TestTreeSitterJava(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="java")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("public class C { int f(int a) { return a; } }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("public class C { int simple(int x) { return x + 1; } }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(JAVA_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("public class N { public static int d(int[] items) {\n"
               "  for (int a : items) { if (a > 0) { while (a > 0) { try {\n"
               "    if (a > 0) { return a; }\n  } finally {} } } }\n  return 0;\n} }")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for(enhanced_for) + if + while + if = 4 decisiones -> cyc 5; try anida sin decisión
        # -> 5 niveles (for>if>while>try>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(JAVA_SAMPLE)}
        self.assertIn("Sample", names)   # constructor_declaration
        self.assertIn("decode", names)   # method_declaration
        self.assertIn("m", names)        # method_declaration
        self.assertIn("r", names)        # lambda_expression vía variable_declarator

    def test_method_and_lambda_params(self):
        fns = {f["function"]: f for f in self.b.measure(JAVA_SAMPLE)}
        self.assertEqual(fns["m"]["parameter_count"], 2)    # method (a, b)
        self.assertEqual(fns["Sample"]["parameter_count"], 1)  # constructor (a)
        self.assertEqual(fns["r"]["parameter_count"], 0)    # lambda sin params

    def test_switch_counting(self):
        src = ("public class C { int s(int x) {\n"
               "  switch (x) { case 0: return 0; case 1: return 1;\n"
               "    case 2: return 2; default: return 3; }\n} }")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 switch_label (case 0,1,2 + default, modelo TS) -> +4 -> cyc 5; switch NO anida
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_java
class TestRoutingJava(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="java").language, "java")
        self.assertEqual(mb.get_backend(extension=".java").language, "java")
        self.assertEqual(mb.get_backend(filename="a.java").language, "java")

    def test_java_registered(self):
        self.assertIn("java", mb.supported_languages())
        self.assertIn(".java", mb.supported_extensions())


@skip_no_java
class TestGateEndToEndJava(unittest.TestCase):
    def test_gate_blocks_critical_java(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "java" / "deep_nesting.java")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.java"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── C# ────────────────────────────────────────────────────────────────────────────────
CSHARP_SAMPLE = """public class Sample {
  public Sample(int a) { this.a = a; }
  public static int Decode(int[] rom, int pc) {
    if (rom != null && pc > 0) { return 1; }
    return 2;
  }
  int M(int a, int b) {
    int add(int c) => a + c;
    System.Func<int,int> lam = (x) => x + 1;
    return add(1) + lam(2);
  }
}
"""


@skip_no_csharp
class TestTreeSitterCSharp(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="csharp")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("public class C { int F(int a) { return a; } }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("public class C { int Simple(int x) { return x + 1; } }")[0]
        self.assertEqual(m["function"], "Simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(CSHARP_SAMPLE) if f["function"] == "Decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("public class N { public static int D(int[] items) {\n"
               "  for (int a = 0; a < items.Length; a++) { if (a > 0) { while (a > 0) { try {\n"
               "    if (a > 0) { return a; }\n  } finally {} } } }\n  return 0;\n} }")
        m = [f for f in self.b.measure(src) if f["function"] == "D"][0]
        # for + if + while + if = 4 decisiones -> cyc 5; try anida sin decisión
        # -> 5 niveles (for>if>while>try>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(CSHARP_SAMPLE)}
        self.assertIn("Sample", names)   # constructor_declaration
        self.assertIn("Decode", names)   # method_declaration
        self.assertIn("M", names)        # method_declaration
        self.assertIn("add", names)      # local_function_statement
        self.assertIn("lam", names)      # lambda_expression vía variable_declarator

    def test_method_localfunc_and_lambda_params(self):
        fns = {f["function"]: f for f in self.b.measure(CSHARP_SAMPLE)}
        self.assertEqual(fns["M"]["parameter_count"], 2)       # method (a, b)
        self.assertEqual(fns["Sample"]["parameter_count"], 1)  # constructor (a)
        self.assertEqual(fns["add"]["parameter_count"], 1)     # local function (c)
        self.assertEqual(fns["lam"]["parameter_count"], 1)     # lambda (x)

    def test_switch_counting(self):
        src = ("public class C { int S(int x) {\n"
               "  switch (x) { case 0: return 0; case 1: return 1;\n"
               "    case 2: return 2; default: return 3; }\n} }")
        m = [f for f in self.b.measure(src) if f["function"] == "S"][0]
        # 4 switch_section (case 0,1,2 + default, modelo TS) -> +4 -> cyc 5; switch NO anida
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_csharp
class TestRoutingCSharp(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="csharp").language, "csharp")
        self.assertEqual(mb.get_backend(extension=".cs").language, "csharp")
        self.assertEqual(mb.get_backend(filename="a.cs").language, "csharp")

    def test_csharp_registered(self):
        self.assertIn("csharp", mb.supported_languages())
        self.assertIn(".cs", mb.supported_extensions())


@skip_no_csharp
class TestGateEndToEndCSharp(unittest.TestCase):
    def test_gate_blocks_critical_csharp(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "csharp" / "deep_nesting.cs")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.cs"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── PHP ───────────────────────────────────────────────────────────────────────────────
PHP_SAMPLE = """<?php
function decode($rom, $pc) {
  if ($rom && $pc) { return 1; }
  return 2;
}
class Sample {
  public function m(int $a, int $b): int {
    $f = fn(int $x) => $x + 1;
    $g = function(int $y) use ($a) { return $y + $a; };
    return $f(1) + $g(2);
  }
  public function __construct(int $a) { $this->a = $a; }
}
"""


@skip_no_php
class TestTreeSitterPHP(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="php")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("<?php function f($a) { return $a; }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("<?php function simple($x) { return $x + 1; }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(PHP_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("<?php\nfunction d($items) {\n"
               "  for ($a = 0; $a < count($items); $a++) { if ($a > 0) { while ($a > 0) { try {\n"
               "    if ($a > 0) { return $a; }\n  } finally {} } } }\n  return 0;\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for + if + while + if = 4 decisiones -> cyc 5; try anida sin decisión
        # -> 5 niveles (for>if>while>try>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(PHP_SAMPLE)}
        self.assertIn("decode", names)        # function_definition
        self.assertIn("m", names)             # method_declaration
        self.assertIn("__construct", names)   # method_declaration (ctor de PHP)
        self.assertIn("f", names)             # arrow_function vía assignment_expression
        self.assertIn("g", names)             # anonymous_function vía assignment_expression

    def test_method_closure_and_arrow_params(self):
        fns = {f["function"]: f for f in self.b.measure(PHP_SAMPLE)}
        self.assertEqual(fns["m"]["parameter_count"], 2)            # method (a, b)
        self.assertEqual(fns["__construct"]["parameter_count"], 1)  # constructor (a)
        self.assertEqual(fns["f"]["parameter_count"], 1)            # arrow fn (x)
        self.assertEqual(fns["g"]["parameter_count"], 1)            # anonymous (y)

    def test_switch_counting(self):
        src = ("<?php\nfunction s($x) {\n"
               "  switch ($x) { case 0: return 0; case 1: return 1;\n"
               "    case 2: return 2; case 3: return 3; }\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 case_statement explícitos (sin default: default_statement no suma, modelo 'ramas − 1')
        # -> +4 -> cyc 5; switch NO anida
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_php
class TestRoutingPHP(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="php").language, "php")
        self.assertEqual(mb.get_backend(extension=".php").language, "php")
        self.assertEqual(mb.get_backend(filename="a.php").language, "php")

    def test_php_registered(self):
        self.assertIn("php", mb.supported_languages())
        self.assertIn(".php", mb.supported_extensions())


@skip_no_php
class TestGateEndToEndPHP(unittest.TestCase):
    def test_gate_blocks_critical_php(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "php" / "deep_nesting.php")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.php"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── Ruby ──────────────────────────────────────────────────────────────────────────────
RUBY_SAMPLE = """def decode(rom, pc)
  if rom && pc
    return 1
  end
  2
end

def self.cls_method(a, b)
  a + b
end

f = ->(x) { x + 1 }
"""


@skip_no_ruby
class TestTreeSitterRuby(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="ruby")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("def f(a)\n  a\nend")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("def simple(x)\n  x + 1\nend")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3 — regresión del filtro is_named: los nodos
        # ruby `if`/`while` comparten type con sus tokens keyword (sin filtro contarían doble).
        m = [f for f in self.b.measure(RUBY_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_verbal_boolops_count(self):
        # and/or verbales cuentan igual que &&/|| (espejo del and/or de Python).
        m = self.b.measure("def t(a, b)\n  a and b or a\nend")[0]
        self.assertEqual(m["cyclomatic"], 3)

    def test_nested_decisions(self):
        src = ("def d(items)\n  for a in items\n    if a\n      while a\n        begin\n"
               "          if a\n            return a\n          end\n        ensure\n"
               "          nil\n        end\n      end\n    end\n  end\n  0\nend\n")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for + if + while + if = 4 decisiones -> cyc 5; begin/ensure es nido sin decisión
        # -> 5 niveles (for>if>while>begin>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(RUBY_SAMPLE)}
        self.assertIn("decode", names)      # method
        self.assertIn("cls_method", names)  # singleton_method
        self.assertIn("f", names)           # lambda literal asignada, vía assignment

    def test_lambda_assigned_params(self):
        # Anónima de contrato: lambda literal `->(x){...}` asignada — nombre y params.
        fns = {f["function"]: f for f in self.b.measure(RUBY_SAMPLE)}
        self.assertEqual(fns["f"]["parameter_count"], 1)
        self.assertEqual(fns["cls_method"]["parameter_count"], 2)

    def test_case_when_counting(self):
        src = ("def s(x)\n  case x\n  when 0\n    0\n  when 1\n    1\n  when 2\n    2\n"
               "  when 3\n    3\n  else\n    9\n  end\nend\n")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 `when` explícitos (+4); else NO suma (nodo propio, modelo 'ramas − 1') -> cyc 5;
        # case NO anida -> nesting 0
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)

    def test_modifier_forms_count(self):
        m = self.b.measure("def t(x)\n  return 1 if x\n  return 2 unless x\nend")[0]
        # if_modifier + unless_modifier -> cyc 3
        self.assertEqual(m["cyclomatic"], 3)

    def test_method_blocks_are_not_functions(self):
        # `lambda {}` / `proc {}` / `.each {}` son calls con block: NO se cuentan como funciones.
        out = self.b.measure("g = lambda { |x| x + 1 }\nitems.each { |i| puts i }\n")
        self.assertEqual(out, [])


@skip_no_ruby
class TestRoutingRuby(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="ruby").language, "ruby")
        self.assertEqual(mb.get_backend(extension=".rb").language, "ruby")
        self.assertEqual(mb.get_backend(filename="a.rb").language, "ruby")

    def test_ruby_registered(self):
        self.assertIn("ruby", mb.supported_languages())
        self.assertIn(".rb", mb.supported_extensions())


@skip_no_ruby
class TestGateEndToEndRuby(unittest.TestCase):
    def test_gate_blocks_critical_ruby(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "ruby" / "deep_nesting.rb")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.rb"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── Kotlin ────────────────────────────────────────────────────────────────────────────
KOTLIN_SAMPLE = """fun decode(rom: ByteArray, pc: Int): Int {
    if (rom.isNotEmpty() && pc > 0) {
        return 1
    }
    return 2
}

val f = { x: Int -> x + 1 }
val g = fun(y: Int): Int { return y + 1 }
"""


@skip_no_kotlin
class TestTreeSitterKotlin(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="kotlin")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("fun f(a: Int): Int { return a }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("fun simple(x: Int): Int { return x + 1 }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(KOTLIN_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("fun d(items: IntArray): Int {\n  for (a in items) {\n    if (a > 0) {\n"
               "      while (a > 0) {\n        try {\n          if (a > 0) { return a }\n"
               "        } finally { }\n      }\n    }\n  }\n  return 0\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for + if + while + if = 4 decisiones -> cyc 5; try/finally anida sin decisión
        # -> 5 niveles (for>if>while>try>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        names = {f["function"] for f in self.b.measure(KOTLIN_SAMPLE)}
        self.assertIn("decode", names)  # function_declaration (name via name_resolver)
        self.assertIn("f", names)       # lambda_literal en val, vía property_declaration
        self.assertIn("g", names)       # anonymous_function en val

    def test_lambda_in_val_params(self):
        # Anónima de contrato: lambda en val — nombre y params (lambda_parameters sin field:
        # regresión del fallback params_node_types; sin él reportaría 0).
        fns = {f["function"]: f for f in self.b.measure(KOTLIN_SAMPLE)}
        self.assertEqual(fns["f"]["parameter_count"], 1)
        self.assertEqual(fns["g"]["parameter_count"], 1)

    def test_when_counting(self):
        src = ("fun s(x: Int): Int {\n  when (x) {\n    0 -> return 0\n    1 -> return 1\n"
               "    2 -> return 2\n    else -> return 3\n  }\n  return -1\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 when_entry (3 ramas + else, un solo tipo de nodo: modelo TS/Java) -> +4 -> cyc 5;
        # when NO anida -> nesting 0
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_kotlin
class TestRoutingKotlin(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="kotlin").language, "kotlin")
        self.assertEqual(mb.get_backend(extension=".kt").language, "kotlin")
        self.assertEqual(mb.get_backend(extension=".kts").language, "kotlin")
        self.assertEqual(mb.get_backend(filename="a.kt").language, "kotlin")

    def test_kotlin_registered(self):
        self.assertIn("kotlin", mb.supported_languages())
        self.assertIn(".kt", mb.supported_extensions())


@skip_no_kotlin
class TestGateEndToEndKotlin(unittest.TestCase):
    def test_gate_blocks_critical_kotlin(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "kotlin" / "deep_nesting.kt")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.kt"
            p.write_text(src, encoding="utf-8")
            env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            r = subprocess.run([sys.executable, str(RUNNERS / "complexity_gate.py"), str(p)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("CRÍTICA", r.stderr)


# ── C ─────────────────────────────────────────────────────────────────────────────────
C_SAMPLE = """int decode(int *rom, int pc) {
    if (rom != 0 && pc > 0) {
        return 1;
    }
    return 2;
}

int *ptr_fn(int a) {
    return 0;
}
"""


@skip_no_c
class TestTreeSitterC(unittest.TestCase):
    def setUp(self):
        self.b = mb.get_backend(language="c")

    def test_shape_matches_lint_results_contract(self):
        m = self.b.measure("int f(int a) { return a; }")[0]
        self.assertEqual(set(m), {"function", "line", "cyclomatic", "nesting_depth",
                                  "parameter_count", "function_length"})
        self.assertEqual(self.b.tool, "ccdd-treesitter-metrics")

    def test_simple_function(self):
        m = self.b.measure("int simple(int x) { return x + 1; }")[0]
        self.assertEqual(m["function"], "simple")
        self.assertEqual(m["cyclomatic"], 1)
        self.assertEqual(m["nesting_depth"], 0)
        self.assertEqual(m["parameter_count"], 1)

    def test_decision_and_boolop_counting(self):
        # if (+1) + && (+1) sobre base 1 = 3
        m = [f for f in self.b.measure(C_SAMPLE) if f["function"] == "decode"][0]
        self.assertEqual(m["cyclomatic"], 3)
        self.assertEqual(m["parameter_count"], 2)

    def test_nested_decisions(self):
        src = ("int d(int n) {\n  for (int a = 0; a < n; a++) {\n    if (a > 0) {\n"
               "      while (a > 0) {\n        cleanup: {\n          if (a > 0) { return a; }\n"
               "        }\n      }\n    }\n  }\n  return 0;\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "d"][0]
        # for + if + while + if = 4 decisiones -> cyc 5; el bloque etiquetado anida sin decisión
        # -> 5 niveles (for>if>while>labeled_statement>if)
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 5)

    def test_name_extraction_variants(self):
        # Nombre vía name_resolver: identifier anidado en el declarator (regresión: sin el
        # hook el nombre sería "<anonymous>"), incluido el retorno puntero (pointer_declarator).
        names = {f["function"] for f in self.b.measure(C_SAMPLE)}
        self.assertIn("decode", names)
        self.assertIn("ptr_fn", names)

    def test_param_count_void_and_variadic(self):
        # Regresiones del hook _c_param_count: sin él, params sería 0 siempre (la lista vive
        # bajo el declarator anidado); `(void)` cuenta 0 y `...` cuenta como slot.
        src = ("int zero(void) { return 0; }\n"
               "int six(int a, int b, int c, int d, int e, int f) { return a; }\n"
               "int var_args(int a, ...) { return a; }\n")
        fns = {f["function"]: f for f in self.b.measure(src)}
        self.assertEqual(fns["zero"]["parameter_count"], 0)
        self.assertEqual(fns["six"]["parameter_count"], 6)
        self.assertEqual(fns["var_args"]["parameter_count"], 2)

    def test_ternary_counts(self):
        m = self.b.measure("int t(int x) { return x ? 1 : 2; }")[0]
        self.assertEqual(m["cyclomatic"], 2)

    def test_switch_counting(self):
        src = ("int s(int x) {\n  switch (x) {\n  case 0: return 0;\n  case 1: return 1;\n"
               "  case 2: return 2;\n  default: return 3;\n  }\n}\n")
        m = [f for f in self.b.measure(src) if f["function"] == "s"][0]
        # 4 case_statement (3 cases + default, un solo tipo de nodo: modelo TS/Java) -> +4
        # -> cyc 5; switch NO anida -> nesting 0
        self.assertEqual(m["cyclomatic"], 5)
        self.assertEqual(m["nesting_depth"], 0)


@skip_no_c
class TestRoutingC(unittest.TestCase):
    def test_routing_by_language_extension_filename(self):
        self.assertEqual(mb.get_backend(language="c").language, "c")
        self.assertEqual(mb.get_backend(extension=".c").language, "c")
        self.assertEqual(mb.get_backend(extension=".h").language, "c")
        self.assertEqual(mb.get_backend(filename="a.c").language, "c")

    def test_c_registered(self):
        self.assertIn("c", mb.supported_languages())
        self.assertIn(".c", mb.supported_extensions())


@skip_no_c
class TestGateEndToEndC(unittest.TestCase):
    def test_gate_blocks_critical_c(self):
        # deep_nesting del fixture: nesting_depth=5 -> CRÍTICA
        deep = (REPO / "fixtures" / "conformance" / "c" / "deep_nesting.c")
        src = deep.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "crit.c"
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
