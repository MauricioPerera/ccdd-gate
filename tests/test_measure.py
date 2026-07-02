"""test_measure.py — tests de measure.py: api_saving_pct honestoy separación
estimado/medido de tokens.

Antes, measure.py reportaba api_saving_pct: 100.0 sobre corridas FALLIDAS y sobre
corridas stub sin llamadas API reales (el 100% salía de que el modelo pequeño cuesta
$0 por definición, no de un ahorro medido). Ahora api_saving_pct es N/A salvo que haya
tokens MEDIDOS (usage real del provider) y al menos un PASS.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import measure as M  # noqa: E402


def _row(result="PASS", tokens="estimated", ours=0.0, loop=0.0,
         attempts=1, escalations=0):
    return {"task": "t", "result": result, "attempts": attempts,
            "escalations": escalations, "tokens": tokens,
            "ours_usd": ours, "big_loop_usd": loop}


class TestSavingHonesty(unittest.TestCase):
    def _totals(self, rows):
        ours, loop, passed, saving = M._aggregate(rows)
        return M._totals(rows, ours, loop, passed, saving)

    def test_no_saving_when_all_fail(self):
        """Corrida sin PASS: api_saving_pct N/A (no 100.0 falso)."""
        totals = self._totals([_row(result="ESCALATE", tokens="estimated")])
        self.assertEqual(totals["passed"], 0)
        self.assertEqual(totals["api_saving_pct"], "N/A")

    def test_no_saving_on_stub_zero_real_spend(self):
        """Stub PASS pero tokens estimados (no hubo API real): N/A, no 100.0."""
        totals = self._totals([_row(result="PASS", tokens="estimated",
                                    ours=0.0, loop=0.045)])
        self.assertEqual(totals["passed"], 1)
        self.assertEqual(totals["api_saving_pct"], "N/A")

    def test_saving_when_measured_spend(self):
        """Tokens MEDIDOS + PASS: se reporta el porcentaje real."""
        totals = self._totals([_row(result="PASS", tokens="measured",
                                    ours=0.01, loop=1.0)])
        self.assertEqual(totals["passed"], 1)
        self.assertEqual(totals["api_saving_pct"], 99.0)

    def test_measured_but_all_fail_still_na(self):
        """Aunque haya tokens medidos, si nada pasó: N/A."""
        totals = self._totals([_row(result="FAIL", tokens="measured",
                                    ours=0.5, loop=1.0)])
        self.assertEqual(totals["api_saving_pct"], "N/A")


class TestTokenKindLabel(unittest.TestCase):
    """summarize_task etiqueta los tokens como estimated/measured/mixed."""

    def test_estimated_for_stub(self):
        r = {"task": "t", "result": "PASS", "attempts": [
            {"by": "stub", "in_tok": 10, "out_tok": 5, "tok_source": "estimated"}]}
        self.assertEqual(M.summarize_task(r)["tokens"], "estimated")

    def test_measured_when_provider_reports_usage(self):
        r = {"task": "t", "result": "PASS", "attempts": [
            {"by": "openai", "in_tok": 100, "out_tok": 50, "tok_source": "measured"}]}
        self.assertEqual(M.summarize_task(r)["tokens"], "measured")

    def test_mixed_when_both_sources_present(self):
        r = {"task": "t", "result": "PASS", "attempts": [
            {"by": "stub", "in_tok": 10, "out_tok": 5, "tok_source": "estimated"},
            {"by": "openai", "in_tok": 100, "out_tok": 50, "tok_source": "measured"}]}
        self.assertEqual(M.summarize_task(r)["tokens"], "mixed")


if __name__ == "__main__":
    unittest.main()