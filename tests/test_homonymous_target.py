"""test_homonymous_target.py — tests CONGELADOS del fix de issue #41: task_gate debe aislar la def
objetivo cuando varias funciones/métodos comparten el nombre, en vez de medir la última (last-wins).

Criterios de aceptación del issue:
  - 2 defs homónimas sin desambiguador  -> INVALID (ambiguo), no un PASS/FAIL silencioso.
  - con target_line correcto            -> mide la def correcta, veredicto estable.
  - un solo match (sin colisión)        -> comportamiento idéntico al histórico.
Determinista, sin LLM."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import metrics    # noqa: E402  (registra backend python + functions_metrics)
import task_gate  # noqa: E402

# Dos clases con método homónimo 'set': Simple (ciclo 1) y Compleja (ciclo 6, nesting 5).
TWO = '''
class Simple:
    def set(self, x):
        return x

class Compleja:
    def set(self, x):
        if x > 0:
            if x > 1:
                if x > 2:
                    if x > 3:
                        if x > 4:
                            return 5
        return 0
'''

ONE = '''
class Simple:
    def set(self, x):
        return x
'''

TEST_FILE = ("import unittest\n"
             "from impl import *\n\n"
             "class T(unittest.TestCase):\n"
             "    def test_set(self):\n"
             "        self.assertEqual(Simple().set(1), 1)\n\n"
             "if __name__ == '__main__':\n"
             "    unittest.main()\n")

CONTRACT = '''---
task: set-target
intent: "Setear un valor en la clase objetivo."
target: impl.py
signature: "def set(self, x)"
{target_line}test_command: "python -m unittest test_x.py"
budget: {{ cyclomatic_max: 2, nesting_max: 1, params_max: 3, lines_max: 10 }}
deps_allowed: []
forbids: ["estado global"]
tests: test_x.py
spec_version: "0.1"
require_test_approval: false
---

## Intent
Setear un valor en la clase objetivo. Exito: pasa los tests y respeta el budget.

## Interface
- in: x. out: depende de la clase.

## Invariants
- Simple().set(x) == x.

## Examples
- Simple().set(1) -> 1
- Simple().set(2) -> 2

## Do / Don't
- DO: devolver el valor. DON'T: estado global.

## Tests
test_x.py: oraculo independiente que importa la clase objetivo.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make(impl, target_line=None):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_FILE, encoding="utf-8")
    tl = f"target_line: {target_line}\n" if target_line is not None else ""
    (d / "task.md").write_text(CONTRACT.format(target_line=tl), encoding="utf-8")
    return d / "task.md"


def _lines(impl):
    """(linea_simple, linea_compleja) según las métricas reales del backend."""
    fns = metrics.functions_metrics(impl)
    simple = next(f["line"] for f in fns if f["cyclomatic"] == 1)
    compleja = next(f["line"] for f in fns if f["cyclomatic"] > 1)
    return simple, compleja


class HomonymousTarget(unittest.TestCase):
    def test_ambiguous_without_disambiguator_is_invalid(self):
        t = _make(TWO)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertEqual(v["stage"], "gate2-complexity")
            self.assertEqual(v["candidate_lines"], sorted(_lines(TWO)))
        finally:
            shutil.rmtree(t.parent)

    def test_target_line_selects_correct_simple_pass(self):
        simple, _ = _lines(TWO)
        t = _make(TWO, target_line=simple)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
            self.assertEqual(v["metrics"]["cyclomatic"], 1)
        finally:
            shutil.rmtree(t.parent)

    def test_target_line_selects_correct_complex_fail(self):
        _, compleja = _lines(TWO)
        t = _make(TWO, target_line=compleja)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate2-complexity")
            self.assertTrue(any("cyclomatic" in o for o in v["over_budget"]))
        finally:
            shutil.rmtree(t.parent)

    def test_single_match_is_backcompat(self):
        t = _make(ONE)  # sin colisión ni target_line: comportamiento idéntico al histórico
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent)

    def test_target_line_no_match_is_invalid(self):
        t = _make(TWO, target_line=999)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertIn("candidate_lines", v)
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
