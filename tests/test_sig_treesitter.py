#!/usr/bin/env python3
"""test_sig_treesitter.py — tests de parse_signature() y check_signature_src() (tree-sitter).

Cubre (segun el task-contract):
- Extraccion nombre+params por lenguaje con gramatica instalada (incluido Go agrupado).
- Mismatch por nombre de param, por cantidad y por nombre de funcion.
- Homonimos con target_line.
- Fallback limpio sin gramatica (simulado con sys.modules["tree_sitter"] = None).
- Camino Python inalterado (mismos veredictos que sig_check).
- Integracion tc_lint.parse_sig con y sin gramatica (warning solo en el fallback).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runners"))

import sig_check
import sig_treesitter
import tc_lint


def _grammar_ok(lang, probe):
    """True si la gramatica del lenguaje esta instalada y parsea el probe."""
    return sig_treesitter.parse_signature(probe, lang) is not None


TS_OK = _grammar_ok("typescript", "function probe(a: string): boolean")
TSX_OK = _grammar_ok("tsx", "function probe(a: string): boolean")
JS_OK = _grammar_ok("javascript", "function probe(a)")
GO_OK = _grammar_ok("go", "func probe(a int) int")
RUST_OK = _grammar_ok("rust", "fn probe(a: i32) -> i32")
JAVA_OK = _grammar_ok("java", "public int probe(int a)")
CSHARP_OK = _grammar_ok("csharp", "public int Probe(int a)")
PHP_OK = _grammar_ok("php", "function probe($a)")


class TestParseSignature(unittest.TestCase):
    """parse_signature(): extraccion de nombre + params por lenguaje."""

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_simple(self):
        got = sig_treesitter.parse_signature("function verify(id: string): boolean", "typescript")
        self.assertEqual(got, {"name": "verify", "params": ["id"]})

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_multiple_params(self):
        got = sig_treesitter.parse_signature("function add(a: number, b: number): number", "typescript")
        self.assertEqual(got, {"name": "add", "params": ["a", "b"]})

    @unittest.skipUnless(TSX_OK, "gramatica tsx no instalada")
    def test_tsx_simple(self):
        got = sig_treesitter.parse_signature("function render(props: Props): JSX.Element", "tsx")
        self.assertEqual(got, {"name": "render", "params": ["props"]})

    @unittest.skipUnless(JS_OK, "gramatica javascript no instalada")
    def test_javascript_simple(self):
        got = sig_treesitter.parse_signature("function sum(a, b)", "javascript")
        self.assertEqual(got, {"name": "sum", "params": ["a", "b"]})

    @unittest.skipUnless(GO_OK, "gramatica go no instalada")
    def test_go_grouped_params(self):
        # Invariante del contrato: func f(a, b int) -> ["a", "b"] (no 1 nodo = 1 param).
        got = sig_treesitter.parse_signature("func f(a, b int)", "go")
        self.assertEqual(got, {"name": "f", "params": ["a", "b"]})

    @unittest.skipUnless(GO_OK, "gramatica go no instalada")
    def test_go_variadic(self):
        got = sig_treesitter.parse_signature("func f(xs ...int)", "go")
        self.assertEqual(got, {"name": "f", "params": ["xs"]})

    @unittest.skipUnless(RUST_OK, "gramatica rust no instalada")
    def test_rust_simple(self):
        got = sig_treesitter.parse_signature("fn compute(x: i32, y: i32) -> i32", "rust")
        self.assertEqual(got, {"name": "compute", "params": ["x", "y"]})

    @unittest.skipUnless(JAVA_OK, "gramatica java no instalada")
    def test_java_method(self):
        got = sig_treesitter.parse_signature("public int add(int a, int b)", "java")
        self.assertEqual(got, {"name": "add", "params": ["a", "b"]})

    @unittest.skipUnless(CSHARP_OK, "gramatica csharp no instalada")
    def test_csharp_method(self):
        got = sig_treesitter.parse_signature("public string Greet(string name)", "csharp")
        self.assertEqual(got, {"name": "Greet", "params": ["name"]})

    @unittest.skipUnless(PHP_OK, "gramatica php no instalada")
    def test_php_function(self):
        got = sig_treesitter.parse_signature("function add($a, $b)", "php")
        self.assertEqual(got["name"], "add")
        self.assertEqual([p.lstrip("$") for p in got["params"]], ["a", "b"])

    def test_invalid_signature_returns_none(self):
        self.assertIsNone(sig_treesitter.parse_signature("not a function at all", "typescript"))

    def test_language_without_langspec_returns_none(self):
        # kotlin no tiene LangSpec en SPECS hoy -> None (fallback anunciado en tc_lint).
        self.assertIsNone(sig_treesitter.parse_signature("fun myFunc(x: Int): Int", "kotlin"))

    def test_no_tree_sitter_returns_none(self):
        # Simula tree_sitter NO instalado: import -> ImportError -> None, sin lanzar.
        with mock.patch.dict(sys.modules, {"tree_sitter": None}):
            got = sig_treesitter.parse_signature("function f(a) {}", "typescript")
        self.assertIsNone(got)


class TestCheckSignatureSrc(unittest.TestCase):
    """check_signature_src(): firma implementada vs esperada."""

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_match(self):
        # Ejemplo del contrato: tipos en la esperada, sin tipos en la impl -> match.
        out = sig_treesitter.check_signature_src(
            "function verify(id) { return true; }", "verify",
            "function verify(id: string): boolean", "typescript")
        self.assertEqual(out, "")

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_param_name_mismatch(self):
        out = sig_treesitter.check_signature_src(
            "function verify(userId) { return true; }", "verify",
            "function verify(id: string)", "typescript")
        self.assertIn("param mismatch", out)
        self.assertIn("id", out)
        self.assertIn("userId", out)

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_param_count_mismatch(self):
        out = sig_treesitter.check_signature_src(
            "function verify(id) { return true; }", "verify",
            "function verify(id: string, token: string)", "typescript")
        self.assertIn("param mismatch", out)

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_typescript_function_name_mismatch(self):
        out = sig_treesitter.check_signature_src(
            "function check(id) { return true; }", "verify",
            "function verify(id: string)", "typescript")
        self.assertIn("function not found", out)

    @unittest.skipUnless(GO_OK, "gramatica go no instalada")
    def test_go_grouped_params_match(self):
        out = sig_treesitter.check_signature_src(
            "func f(a, b int) int { return a + b }", "f",
            "func f(a, b int) int", "go")
        self.assertEqual(out, "")

    @unittest.skipUnless(GO_OK, "gramatica go no instalada")
    def test_go_grouped_params_mismatch(self):
        out = sig_treesitter.check_signature_src(
            "func f(x, y int) int { return x + y }", "f",
            "func f(a, b int) int", "go")
        self.assertIn("param mismatch", out)

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_homonym_with_target_line(self):
        src = ("function f(x) { return 1; }\n"
               "function f(x, y) { return 2; }\n")
        # target_line=2 apunta a la segunda def (2 params): la esperada de 2 params matchea.
        out2 = sig_treesitter.check_signature_src(src, "f", "function f(x, y)", "typescript",
                                                  target_line=2)
        self.assertEqual(out2, "")
        # Sin target_line se toma la PRIMERA (1 param): la esperada de 2 params NO matchea.
        out1 = sig_treesitter.check_signature_src(src, "f", "function f(x, y)", "typescript")
        self.assertIn("param mismatch", out1)

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_function_not_found(self):
        out = sig_treesitter.check_signature_src(
            "function other(x) { return x; }", "unknown",
            "function unknown(x)", "typescript")
        self.assertIn("function not found", out)

    def test_no_grammar_reports_error_string(self):
        out = sig_treesitter.check_signature_src("fun f(x: Int) {}", "f", "fun f(x: Int)", "kotlin")
        self.assertNotEqual(out, "")


class TestPythonUnchanged(unittest.TestCase):
    """El camino Python queda INTACTO: mismos veredictos que sig_check (AST nativo)."""

    def test_python_match_via_sig_check(self):
        out = sig_check.signature_mismatch("def add(a, b):\n    return a + b", "add",
                                           "def add(a: int, b: int) -> int")
        self.assertEqual(out, "")

    def test_python_param_mismatch_via_sig_check(self):
        out = sig_check.signature_mismatch("def f(y):\n    return y", "f", "def f(x: int)")
        self.assertIn("param mismatch", out)

    def test_tc_lint_python_uses_native_ast(self):
        # parse_sig python: identico al AST nativo, no pasa por tree-sitter.
        self.assertEqual(tc_lint.parse_sig("def add(a: int, b: int) -> int", "python"), ("add", 2))


class TestTcLintIntegration(unittest.TestCase):
    """tc_lint.parse_sig / r_signature: tree-sitter primero, fallback anunciado."""

    @staticmethod
    def _ctx(sig, lang):
        return {"fm": {"signature": sig}, "language": lang, "budget": {}, "fn_name": None}

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_parse_sig_ts_uses_treesitter(self):
        self.assertEqual(tc_lint.parse_sig("function verify(id: string): boolean", "typescript"),
                         ("verify", 1))

    @unittest.skipUnless(GO_OK, "gramatica go no instalada")
    def test_parse_sig_go_grouped_arity(self):
        self.assertEqual(tc_lint.parse_sig("func f(a, b int)", "go"), ("f", 2))

    @unittest.skipUnless(TS_OK, "gramatica typescript no instalada")
    def test_no_warning_with_grammar(self):
        findings = tc_lint.r_signature(self._ctx("function g(a, b)", "typescript"))
        rules = [f["rule"] for f in findings]
        self.assertNotIn("tc-signature-generic", rules)

    def test_warning_on_fallback_without_grammar(self):
        # Simula tree_sitter ausente: mismo contrato TS -> fallback generico + warning.
        with mock.patch.dict(sys.modules, {"tree_sitter": None}):
            findings = tc_lint.r_signature(self._ctx("function g(a, b)", "typescript"))
        rules = [f["rule"] for f in findings]
        self.assertIn("tc-signature-generic", rules)

    def test_kotlin_falls_back_with_warning(self):
        # kotlin sin LangSpec hoy: aridad generica + warning (como antes de esta tarea).
        name, arity = tc_lint.parse_sig("fun myFunc(x: Int, y: String)", "kotlin")
        self.assertEqual((name, arity), ("myFunc", 2))
        findings = tc_lint.r_signature(self._ctx("fun myFunc(x: Int, y: String)", "kotlin"))
        rules = [f["rule"] for f in findings]
        self.assertIn("tc-signature-generic", rules)

    def test_parse_sig_fallback_without_treesitter(self):
        # Sin tree_sitter, parse_sig no lanza: cae al generico y extrae nombre+aridad.
        with mock.patch.dict(sys.modules, {"tree_sitter": None}):
            name, arity = tc_lint.parse_sig("function g(a, b, c)", "typescript")
        self.assertEqual((name, arity), ("g", 3))


if __name__ == "__main__":
    unittest.main()
