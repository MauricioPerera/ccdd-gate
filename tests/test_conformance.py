"""test_conformance.py — suite de CONFORMANCIA de métricas cross-lenguaje (#8). Sin LLM.

Oráculo congelado en fixtures/conformance/manifest.json. Cada backend registrado debe reproducir
los valores esperados de cada fixture para el que tenga fuente. Python define el baseline; un
backend nuevo (p. ej. tree-sitter/TS, #1) no se da por bueno hasta pasar esta suite.

Métricas estructurales (cyclomatic, nesting_depth, parameter_count) deben coincidir entre lenguajes
para la misma estructura lógica; function_length (y divergencias declaradas) se comparan por-lenguaje
vía `language_overrides`.
"""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import metrics_backends as mb  # noqa: E402

CONF = REPO / "fixtures" / "conformance"
MANIFEST = json.loads((CONF / "manifest.json").read_text(encoding="utf-8"))
METRICS = ("cyclomatic", "nesting_depth", "parameter_count", "function_length")


def expected_for(fixture, language):
    """Valor esperado por métrica para un lenguaje: expected + language_overrides[language]."""
    exp = dict(fixture["expected"])
    exp.update(fixture.get("language_overrides", {}).get(language, {}))
    return exp


def measure_target(language, source_rel, target):
    src = (CONF / source_rel).read_text(encoding="utf-8")
    fns = [f for f in mb.get_backend(language=language).measure(src) if f["function"] == target]
    return fns[0] if fns else None


class TestManifestWellFormed(unittest.TestCase):
    def test_required_fixtures_present(self):
        ids = {f["id"] for f in MANIFEST["fixtures"]}
        for required in ("simple", "deep_nesting", "many_params", "long_function",
                         "boolop_chain", "comprehension", "switch_case"):
            self.assertIn(required, ids)

    def test_every_fixture_has_full_expected(self):
        for f in MANIFEST["fixtures"]:
            self.assertEqual(set(f["expected"]), set(METRICS), f["id"])


class TestConformance(unittest.TestCase):
    """Parametrizado por (lenguaje, fixture) sobre todo backend registrado con fuente disponible."""

    def test_all_backends_match_oracle(self):
        checked = 0
        for fixture in MANIFEST["fixtures"]:
            for language, source_rel in fixture.get("sources", {}).items():
                if language not in mb.supported_languages():
                    continue  # backend aún no implementado: se valida cuando exista
                with self.subTest(language=language, fixture=fixture["id"]):
                    m = measure_target(language, source_rel, fixture["target"])
                    self.assertIsNotNone(m, f"{language}/{fixture['id']}: target no encontrado")
                    exp = expected_for(fixture, language)
                    for metric in METRICS:
                        self.assertEqual(
                            m[metric], exp[metric],
                            f"{language}/{fixture['id']}: {metric}={m[metric]} != oráculo {exp[metric]}")
                    checked += 1
        self.assertGreater(checked, 0, "ningún backend/fixture verificado")

    def test_python_baseline_is_complete(self):
        # Python (baseline) debe tener fuente y pasar TODOS los fixtures.
        for fixture in MANIFEST["fixtures"]:
            self.assertIn("python", fixture.get("sources", {}), fixture["id"])
            m = measure_target("python", fixture["sources"]["python"], fixture["target"])
            exp = expected_for(fixture, "python")
            self.assertEqual({k: m[k] for k in METRICS}, exp, fixture["id"])


if __name__ == "__main__":
    unittest.main()
