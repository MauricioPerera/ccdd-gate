"""test_language_guardrails.py — tests CONGELADOS de guardrails language-aware (#6). Sin LLM.

Aceptación de la issue:
  - scan_guardrails aplica texto-puro (secretos) + estructurales con el backend del lenguaje
    + específicos del lenguaje si existen.
  - Secrets dispara igual en cualquier lenguaje.
  - Sin language, comportamiento python (deep-nesting calculado con el backend python).
  - Sin backend para el lenguaje, deep-nesting degrada al regex (no se pierde el guardrail).
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import complexity_mcp as m  # noqa: E402

SECRET = 'KEY = "sk-ABCDEFGHIJKLMNOPQRSTUVWX"'
DEEP_PY = "def f(a):\n    if a:\n        for i in a:\n            while i:\n                if i:\n                    return 1\n"


def fired(result):
    return {g["id"]: g for g in result["guardrails"]}


class TestSharedTextGuardrails(unittest.TestCase):
    def test_secrets_block_in_any_language(self):
        for lang in ("python", "typescript", "go"):
            r = m.scan_guardrails({"code": SECRET, "language": lang})
            g = fired(r)["no-secrets"]
            self.assertTrue(g["fired"], lang)
            self.assertTrue(r["blocked"], lang)         # on_fail abort
            self.assertEqual(g["method"], "regex")


class TestStructuralViaBackend(unittest.TestCase):
    def test_deep_nesting_uses_python_backend_by_default(self):
        r = m.scan_guardrails({"code": DEEP_PY})
        g = fired(r)["deep-nesting"]
        self.assertEqual(r["language"], "python")       # back-compat: default python
        self.assertTrue(g["fired"])
        self.assertEqual(g["method"], "backend")        # estructural, no regex

    def test_shallow_python_does_not_fire(self):
        r = m.scan_guardrails({"code": "def f(a):\n    return a\n"})
        self.assertFalse(fired(r)["deep-nesting"]["fired"])
        self.assertEqual(fired(r)["deep-nesting"]["method"], "backend")

    def test_no_backend_falls_back_to_regex(self):
        # Lenguaje sin backend de métricas: el guardrail estructural no se pierde, cae al regex.
        # (swift no tiene backend registrado; ruby lo tiene desde TAREA-RKC, go/rust desde antes,
        # así que ya no sirven como ejemplo "sin backend" — misma rotación que fb3977a go→ruby.)
        deep_indent = "\t\t\t\tx = 1\n"
        r = m.scan_guardrails({"code": deep_indent, "language": "swift"})
        g = fired(r)["deep-nesting"]
        self.assertEqual(g["method"], "regex")
        self.assertTrue(g["fired"])

    def test_syntax_error_python_falls_back_to_regex(self):
        r = m.scan_guardrails({"code": "                x = (", "language": "python"})
        self.assertEqual(fired(r)["deep-nesting"]["method"], "regex")  # no parsea -> regex


class TestLanguageSpecificGuardrails(unittest.TestCase):
    def test_no_eval_python(self):
        r = m.scan_guardrails({"code": "y = eval('1+1')", "language": "python"})
        self.assertTrue(fired(r)["no-eval"]["fired"])

    def test_no_eval_typescript_new_function(self):
        r = m.scan_guardrails({"code": "const f = new Function('x')", "language": "typescript"})
        self.assertTrue(fired(r)["no-eval"]["fired"])

    def test_python_no_eval_does_not_match_new_function(self):
        # patrón python (eval/exec) NO matchea el new Function de JS
        r = m.scan_guardrails({"code": "const f = new Function('x')", "language": "python"})
        self.assertFalse(fired(r)["no-eval"]["fired"])

    def test_language_resolved_from_filename(self):
        r = m.scan_guardrails({"code": "new Function('x')", "filename": "a.ts"})
        self.assertEqual(r["language"], "typescript")
        self.assertTrue(fired(r)["no-eval"]["fired"])


if __name__ == "__main__":
    unittest.main()
