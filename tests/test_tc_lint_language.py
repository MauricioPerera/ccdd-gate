"""test_tc_lint_language.py — tests CONGELADOS del campo `language` y la validación de firma
por lenguaje (#4). Sin LLM. Cubre la aceptación de la issue:
  - language: typescript con firma TS válida pasa tc-signature-valid y respeta params_max.
  - sin language, comportamiento idéntico al actual (python, sin warning genérico).
  - language inválido dispara tc-language; firma no parseable dispara tc-signature-valid.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import tc_lint  # noqa: E402

# Contrato TS completo y válido (estructura mínima que pasa todas las reglas de tc_lint).
TS_CONTRACT = """---
task: decode-ts
intent: "Decodificar una instrucción."
target: decode.ts
signature: "function decode(rom: Uint8Array, pc: number): [string, string, number]"
budget: { cyclomatic_max: 8, nesting_max: 2, params_max: 2, lines_max: 20 }
deps_allowed: []
forbids: ["while", "estado global"]
tests: decode.test.ts
language: typescript
spec_version: "0.1"
---

## Intent
Dada la ROM y `pc`, devolver `[hex, texto, size]`.

## Interface
```
in:  rom, pc
out: [hex, texto, size]
```

## Invariants
- size en {1,2,3}.

## Examples
- decode(rom, 0) -> ["00", "NOP", 1]
- decode(rom, 1) -> ["C3", "JP", 3]

## Do / Don't
- DO: tabla de despacho.
- DON'T: while.

## Tests
Property-test congelado en decode.test.ts.

## Constraints
- PARAR y reportar si el budget no alcanza sin violar la interfaz.
"""


def _write(contract, sig=None, language="__keep__", fn_name="decode"):
    d = Path(tempfile.mkdtemp())
    text = contract
    if sig is not None:
        text = text.replace(
            'signature: "function decode(rom: Uint8Array, pc: number): [string, string, number]"',
            f'signature: "{sig}"')
    if language != "__keep__":
        text = (text.replace("language: typescript\n", "")
                if language is None else text.replace("language: typescript", f"language: {language}"))
    task = d / "task.md"
    task.write_text(text, encoding="utf-8")
    (d / "decode.test.ts").write_text(f"// frozen tests for {fn_name}\n", encoding="utf-8")
    return d, task


def _rules(task, level):
    return {f["rule"] for f in tc_lint.lint(str(task)) if f["level"] == level}


class TestParseSigGeneric(unittest.TestCase):
    def test_arity_and_name_across_languages(self):
        cases = [
            ("typescript", "function decode(rom: Uint8Array, pc: number): R", ("decode", 2)),
            ("typescript", "decode<T>(a: Map<string, number>, b: T[]): R", ("decode", 2)),
            ("typescript", "const f = async (a, b, c) =>", ("f", 3)),
            ("go", "func Decode(rom []byte, pc int) (string, int)", ("Decode", 2)),
            ("rust", "fn parse(a: i32, b: Vec<(i32, i32)>) -> bool", ("parse", 2)),
            ("java", "public int sum(int a, int b)", ("sum", 2)),
            ("typescript", "noargs()", ("noargs", 0)),
        ]
        for lang, sig, expected in cases:
            self.assertEqual(tc_lint.parse_sig(sig, lang), expected, sig)

    def test_invalid_signature_raises(self):
        with self.assertRaises(ValueError):
            tc_lint.parse_sig("garbage sin parens", "typescript")

    def test_python_path_unchanged(self):
        self.assertEqual(
            tc_lint.parse_sig("def decode_instruction(rom: bytes, pc: int) -> tuple", "python"),
            ("decode_instruction", 2))
        # sin language -> default python
        self.assertEqual(tc_lint.parse_sig("def f(a, b)"), ("f", 2))


class TestLanguageInLint(unittest.TestCase):
    def test_valid_ts_contract_no_errors(self):
        d, task = _write(TS_CONTRACT)
        try:
            errs = _rules(task, "error")
            warns = _rules(task, "warn")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(errs, set(), errs)              # firma TS válida: sin errores
        self.assertIn("tc-signature-generic", warns)     # degradación documentada con warning

    def test_params_max_enforced_for_ts(self):
        d, task = _write(TS_CONTRACT, sig="function decode(a: number, b: number, c: number): R")
        try:
            findings = tc_lint.lint(str(task))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        sig_errs = [f for f in findings if f["rule"] == "tc-signature-valid" and f["level"] == "error"]
        self.assertTrue(any("params" in f["msg"] for f in sig_errs), findings)

    def test_unparseable_ts_signature_errors(self):
        d, task = _write(TS_CONTRACT, sig="esto no tiene parametros")
        try:
            errs = _rules(task, "error")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIn("tc-signature-valid", errs)

    def test_invalid_language_value_errors(self):
        d, task = _write(TS_CONTRACT, language='""')  # string vacío
        try:
            errs = _rules(task, "error")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIn("tc-language", errs)

    def test_no_generic_warning_for_python(self):
        # El sandbox python existente NO debe emitir el warning genérico de firma.
        warns = {f["rule"] for f in tc_lint.lint(REPO / "examples" / "sandbox" / "task.md")
                 if f["level"] == "warn"}
        self.assertNotIn("tc-signature-generic", warns)


if __name__ == "__main__":
    unittest.main()
