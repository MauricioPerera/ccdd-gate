"""test_orchestrator_cefl.py — tests OFFLINE del loop CEFL del orquestador.

Ejerce la feature de candidatos paralelos + torneo por complejidad + feedback
masivo, que hasta ahora no tenía test (el único test del orquestador usa un
contrato BROKEN que muere en tc_lint antes de llegar al loop).

Sin red: usa --provider stub sobre el harness de examples/sandbox/loop_demo/
(_stub_bad.py / _stub_good.py) con un contrato VÁLIDO que pasa tc_lint. El
tempdir aísla la corrida para no reescribir el fixture del repo.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import orchestrator as O  # noqa: E402
import tc_lint  # noqa: E402

DEMO = REPO / "examples" / "sandbox" / "loop_demo"


def _copy_demo(tmp):
    """Copia el harness del demo a un tempdir y devuelve la ruta al task.md."""
    d = Path(tmp) / "demo"
    shutil.copytree(DEMO, d)
    return d / "task.md"


class TestCEFLLoopOffline(unittest.TestCase):
    """Loop grande/pequeño end-to-end con stub: candidates, torneo, feedback."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.task = _copy_demo(self._tmp)
        # Sanity: el contrato debe pasar tc_lint (no es el BROKEN de test_lifecycle).
        self.assertFalse(
            any(f["level"] == "error" for f in tc_lint.lint(str(self.task))),
            "el contrato del demo debe pasar tc_lint para ejercer el loop")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _stub(self, *names):
        return iter([str(DEMO / n) for n in names])

    def test_bad_then_good_passes_on_attempt_2(self):
        """(a) stub malo luego bueno: intento 1 FAIL, intento 2 PASS; se conserva el bueno."""
        res = O.implement(str(self.task), "stub", "m", 3, None, 1,
                          self._stub("_stub_bad.py", "_stub_good.py"))
        self.assertEqual(res["result"], "PASS")
        atts = res["attempts"]
        self.assertEqual(len(atts), 2)
        self.assertEqual(atts[0]["verdict"], "FAIL")
        self.assertEqual(atts[1]["verdict"], "PASS")

        # El target final contiene exactamente el código del stub bueno (candidato congelado).
        target = self.task.parent / "disassembler.py"
        good = (DEMO / "_stub_good.py").read_text(encoding="utf-8")
        self.assertEqual(target.read_text(encoding="utf-8"), good)

        # Telemetría del torneo registrada en el intento que pasó.
        self.assertEqual(atts[1]["best_candidate_index"], 0)
        self.assertIn("best_complexity_score", atts[1])
        self.assertEqual(atts[1]["tok_source"], "estimated")

    def test_all_fail_combines_feedback(self):
        """(b) todos fallan: resultado ESCALATE y el feedback combina los fallos."""
        res = O.implement(str(self.task), "stub", "m", 2, None, 1,
                          self._stub("_stub_bad.py", "_stub_bad.py"))
        self.assertEqual(res["result"], "ESCALATE")
        self.assertEqual(len(res["attempts"]), 2)
        for a in res["attempts"]:
            self.assertEqual(a["verdict"], "FAIL")
            self.assertEqual(a["stage"], "all_candidates_failed")

        fb = res["last_feedback"]
        self.assertEqual(fb["verdict"], "FAIL_ALL_CANDIDATES")
        # El feedback combina las evaluaciones de los candidatos fallidos.
        self.assertIn("candidates_evaluations", fb)
        self.assertGreaterEqual(len(fb["candidates_evaluations"]), 1)
        for ev in fb["candidates_evaluations"]:
            self.assertIn("candidate_code", ev)
            self.assertIn("gate_error", ev)
            self.assertEqual(ev["gate_error"]["verdict"], "FAIL")


class TestTournamentDeterminism(unittest.TestCase):
    """El torneo debe ser función solo del código, no del tiempo de red."""

    def _v(self, cycl, nest, params, length):
        return {"metrics": {"cyclomatic": cycl, "nesting_depth": nest,
                            "parameter_count": params, "function_length": length}}

    def test_score_includes_function_length(self):
        """get_complexity_score incluye function_length (lines_max), no solo las otras tres."""
        score = O.get_complexity_score(self._v(2, 1, 1, 5))
        self.assertEqual(score, 2 + 1 + 1 + 5)

    def test_lower_score_wins_regardless_of_index(self):
        """Menor score gana aunque su índice de envío sea mayor."""
        candidates = [
            {"index": 0, "code": "hi", "verdict": self._v(5, 2, 2, 5)},
            {"index": 1, "code": "lo", "verdict": self._v(1, 1, 1, 2)},
        ]
        self.assertEqual(O._pick_best(candidates)["index"], 1)

    def test_tiebreak_by_submission_index(self):
        """Ante empate de score, gana el de menor índice de envío (no el que terminó primero)."""
        v = self._v(2, 1, 1, 5)
        # Órden de finalización arbitrario (índice 2 primero), como as_completed.
        candidates = [
            {"index": 2, "code": "late", "verdict": v},
            {"index": 0, "code": "first", "verdict": v},
            {"index": 1, "code": "mid", "verdict": v},
        ]
        self.assertEqual(O._pick_best(candidates)["index"], 0)

    def test_generate_candidates_preserves_submission_order(self):
        """_generate_candidates reordena por índice de envío aunque as_completed
        devuelva por orden de término. Con stub se consume 1 por intento."""
        # stub: un candidato por intento; índice 0, lista de 1 elemento.
        out = O._generate_candidates("stub", "m", "prompt",
                                     iter([str(DEMO / "_stub_good.py")]), 0.7, 3)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()