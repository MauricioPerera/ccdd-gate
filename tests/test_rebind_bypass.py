"""test_rebind_bypass.py — tests CONGELADOS del fix RB1.1: anti-rebind del nombre target.

El gate mide la `def f` estática por nombre; si el módulo hace `f = _real` a nivel de módulo,
en runtime `f` es OTRA función NO medida y el gate daría PASS midiendo la cáscara trivial
(bypass del arbitre). El gate debe detectar la reasignación a nivel de módulo y devolver
INVALID/gate-rebind. Determinista, sin LLM.

Criterios:
  - target con `f = _real` (real complejo) -> INVALID/gate-rebind (antes PASS midiendo la cáscara).
  - target normal sin rebind               -> PASS (control).
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
task: rebind-demo
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
require_test_approval: false
---

## Intent
Devolver x. Exito: pasa tests, budget y sin rebind.

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

# Cáscara trivial (cyclomatic 1) + real complejo (9 ifs, viola budget) + rebind a nivel de módulo.
# En runtime `f` es _real; el gate estático mide la cáscara y daría PASS sin el gate de rebind.
REBIND_IMPL = (
    "def f(x):\n"
    "    return x\n"
    "\n"
    "def _real(x):\n"
    "    if x == 1:\n"
    "        if x >= 1:\n"
    "            if x <= 1:\n"
    "                if x > 0:\n"
    "                    if x < 2:\n"
    "                        if x != 0:\n"
    "                            if x != 2:\n"
    "                                if x + 1 == 2:\n"
    "                                    if x - 1 == 0:\n"
    "                                        return 1\n"
    "    return 0\n"
    "\n"
    "f = _real\n"
)

PLAIN_IMPL = "def f(x):\n    return x\n"


def _make(impl_src):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl_src, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    (d / "task.md").write_text(CONTRACT, encoding="utf-8")
    return d / "task.md"


class RebindBypass(unittest.TestCase):
    def test_rebind_is_invalid_gate_rebind(self):
        t = _make(REBIND_IMPL)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "INVALID", v)
            self.assertEqual(v["stage"], "gate-rebind", v)
        finally:
            shutil.rmtree(t.parent, ignore_errors=True)

    def test_plain_target_without_rebind_passes(self):
        t = _make(PLAIN_IMPL)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()