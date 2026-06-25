"""test_signature_gate.py — tests CONGELADOS de la etapa gate-signature de task_gate: la firma
IMPLEMENTADA debe coincidir (nombre + nombres de parámetros en orden) con la `signature` del
contrato. Default-on (toda función con signature). Sin LLM. Define el contrato para la integración:

  - impl con nombre de parámetro distinto al de la firma -> FAIL, stage 'gate-signature'
  - impl que coincide con la firma                       -> PASS
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import task_gate  # noqa: E402

TEST_X = ("import unittest\n"
          "from impl import f\n\n"
          "class T(unittest.TestCase):\n"
          "    def test_f(self):\n"
          "        self.assertEqual(f(1), 1)\n\n"
          "if __name__ == '__main__':\n"
          "    unittest.main()\n")

CONTRACT = '''---
task: sig-demo
intent: "Devolver el valor recibido."
target: impl.py
signature: "def f(x)"
test_command: "python -m unittest test_x"
test_cwd: "."
budget: { cyclomatic_max: 3, nesting_max: 1, params_max: 1, lines_max: 10 }
deps_allowed: []
forbids: ["estado global"]
tests: test_x.py
spec_version: "0.1"
---

## Intent
Devolver x. Exito: pasa los tests, el budget y la conformidad de firma.

## Interface
- in: x. out: x.

## Invariants
- f(x) == x.

## Examples
- f(1) -> 1
- f(2) -> 2

## Do / Don't
- DO: devolver el argumento. DON'T: estado global.

## Tests
test_x.py: oraculo independiente.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make(impl_src):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl_src, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    (d / "task.md").write_text(CONTRACT, encoding="utf-8")
    return d / "task.md"


class SignatureGate(unittest.TestCase):
    def test_mismatch_blocks(self):
        t = _make("def f(a):\n    return a\n")  # firma del contrato dice (x); impl usa (a)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-signature")
            self.assertTrue(v.get("mismatch"))
        finally:
            shutil.rmtree(t.parent)

    def test_match_passes(self):
        t = _make("def f(x):\n    return x\n")
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent)


# Target con dos `f` homónimas: f@L1 (a) y f@L4 (x). Ambas devuelven su arg -> f(1)==1 sea cual sea
# la última en el módulo, así el gate de tests pasa y lo que decide es target_line.
HOMONYMS = "def f(a):\n    return a\n\ndef f(x):\n    return x\n"  # f(a)@L1, f(x)@L4


def _make_homonyms(target_line):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(HOMONYMS, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    contract = CONTRACT.replace('signature: "def f(x)"\n',
                                f'signature: "def f(x)"\ntarget_line: {target_line}\n')
    (d / "task.md").write_text(contract, encoding="utf-8")
    return d / "task.md"


class SignatureGateTargetLine(unittest.TestCase):
    def test_target_line_match_passes(self):
        t = _make_homonyms(target_line=4)  # apunta a f(x): coincide con la firma
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)

    def test_target_line_mismatch_blocks(self):
        t = _make_homonyms(target_line=1)  # apunta a f(a): difiere de la firma (x)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-signature")
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
