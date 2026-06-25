"""test_purity_gate.py — tests CONGELADOS de la etapa gate-purity de task_gate (opt-in `pure: true`):
si el contrato declara la función pura, el gate falla cuando el cuerpo tiene operaciones impuras
(print/open/eval/global/import/...). Sin LLM. Default-off (sin `pure` no corre)."""
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
task: purity-demo
intent: "Devolver el valor recibido."
target: impl.py
signature: "def f(x)"
test_command: "python -m unittest test_x"
test_cwd: "."
budget: {{ cyclomatic_max: 3, nesting_max: 1, params_max: 1, lines_max: 10 }}
deps_allowed: []
forbids: ["estado global"]
tests: test_x.py
spec_version: "0.1"
{pure}---

## Intent
Devolver x. Exito: pasa tests, budget y pureza si se exige.

## Interface
- in: x. out: x.

## Invariants
- f(x) == x.

## Examples
- f(1) -> 1
- f(2) -> 2

## Do / Don't
- DO: devolver x. DON'T: estado global.

## Tests
test_x.py: oraculo independiente.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make(impl_src, pure=False):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl_src, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    (d / "task.md").write_text(CONTRACT.format(pure="pure: true\n" if pure else ""), encoding="utf-8")
    return d / "task.md"


IMPURE = "def f(x):\n    print(x)\n    return x\n"
PURE = "def f(x):\n    return x\n"


class PurityGate(unittest.TestCase):
    def test_impure_blocks_when_pure_required(self):
        t = _make(IMPURE, pure=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-purity")
            self.assertIn("print", v.get("impurities", []))
        finally:
            shutil.rmtree(t.parent)

    def test_pure_passes_when_pure_required(self):
        t = _make(PURE, pure=True)
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)

    def test_optin_off_is_backcompat(self):
        t = _make(IMPURE, pure=False)  # sin `pure`: la etapa no corre aunque el código sea impuro
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
