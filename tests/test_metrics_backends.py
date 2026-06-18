"""test_metrics_backends.py — tests CONGELADOS del registro pluggable de backends (#3). Sin LLM.

Cubre las tres condiciones de aceptación de la issue:
  1) Existe un punto único get_backend(language|extension) que devuelve el extractor.
  2) Python da EXACTAMENTE los mismos números (regresión cero) — valores oráculo congelados.
  3) Añadir un lenguaje = registrar un backend (capa neutral comparte severity/umbrales/shape).
"""
import unittest

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import metrics            # noqa: E402
import metrics_backends as mb  # noqa: E402

NESTED = """
def f(a, b, c, d, e, g):
    for i in a:
        if i:
            while b:
                try:
                    if c and d or e:
                        return [x for x in i if x]
                except Exception:
                    pass
"""


class TestPythonRegression(unittest.TestCase):
    """Valores oráculo congelados: el backend Python no puede cambiar números sin que esto falle."""

    def test_nested_fixture_frozen(self):
        fns = metrics.functions_metrics(NESTED)
        self.assertEqual(fns, [{
            "function": "f", "line": 2, "cyclomatic": 10,
            "nesting_depth": 5, "parameter_count": 6, "function_length": 9,
        }])

    def test_extract_source_shape_and_values(self):
        es = metrics.extract_source(NESTED, "f.py")
        self.assertEqual(es["tool"], "ccdd-ast-metrics")
        self.assertEqual(es["version"], "1")
        self.assertIn("timestamp", es)
        by_metric = {f["metric"]: f for f in es["findings"]}
        # nesting_depth=5 -> CRÍTICA; parameter_count=6 -> MEDIA (>=RED); cyclomatic=10 -> INFO (amber, <RED)
        self.assertEqual(by_metric["nesting_depth"]["severity"], "CRÍTICA")
        self.assertTrue(by_metric["nesting_depth"]["exceeds_threshold"])
        self.assertEqual(by_metric["parameter_count"]["severity"], "MEDIA")
        self.assertEqual(by_metric["cyclomatic"]["severity"], "INFO")
        self.assertFalse(by_metric["cyclomatic"]["exceeds_threshold"])

    def test_syntax_error_returns_parse_error(self):
        es = metrics.extract_source("def (", "bad.py")
        self.assertEqual(es["findings"], [])
        self.assertIn("parse_error", es)


class TestRegistry(unittest.TestCase):
    """Punto único get_backend con precedencia language > extension > filename > default."""

    def test_python_registered_by_default(self):
        self.assertIn("python", mb.supported_languages())
        self.assertIn(".py", mb.supported_extensions())

    def test_resolution_paths_all_python(self):
        self.assertEqual(mb.get_backend(language="python").language, "python")
        self.assertEqual(mb.get_backend(extension=".py").language, "python")
        self.assertEqual(mb.get_backend(extension=".PY").language, "python")  # case-insensitive
        self.assertEqual(mb.get_backend(filename="mod.pyi").language, "python")
        self.assertEqual(mb.get_backend().language, "python")  # default back-compat

    def test_unknown_language_raises(self):
        with self.assertRaises(KeyError):
            mb.get_backend(language="klingon")
        with self.assertRaises(KeyError):
            mb.get_backend(extension=".cobol")

    def test_generic_helpers_match_python_backend(self):
        self.assertEqual(mb.functions_metrics(NESTED), metrics.functions_metrics(NESTED))


class TestSharedLayer(unittest.TestCase):
    """severity y umbrales son ÚNICOS y compartidos; un backend nuevo los reusa sin duplicar."""

    def test_severity_is_single_source(self):
        self.assertIs(metrics.severity, mb.severity)

    def test_thresholds_are_single_source(self):
        self.assertIs(metrics._AMBER, mb.AMBER)
        self.assertIs(metrics._RED, mb.RED)

    def test_new_backend_reuses_shared_assembly(self):
        # Backend ficticio que mide "a mano": prueba que registrar = enchufar, sin tocar nada más.
        class FakeBackend(mb.Backend):
            language = "fake"
            extensions = (".fake",)
            tool = "fake-tool"
            version = "9"

            def measure(self, src):
                return [{"function": "huge", "line": 1, "cyclomatic": 25,
                         "nesting_depth": 1, "parameter_count": 1, "function_length": 5}]

        try:
            mb.register(FakeBackend())
            b = mb.get_backend(language="fake")
            self.assertEqual(mb.get_backend(extension=".fake").language, "fake")
            es = b.extract_source("whatever", "x.fake")
            self.assertEqual(es["tool"], "fake-tool")
            self.assertEqual(es["version"], "9")
            # severidad calculada con la capa COMPARTIDA: cyclomatic=25 (>20) -> CRÍTICA
            f = next(f for f in es["findings"] if f["metric"] == "cyclomatic")
            self.assertEqual(f["severity"], "CRÍTICA")
            self.assertTrue(f["exceeds_threshold"])
        finally:
            mb._BY_LANG.pop("fake", None)
            mb._BY_EXT.pop(".fake", None)


if __name__ == "__main__":
    unittest.main()
