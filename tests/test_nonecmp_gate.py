"""test_nonecmp_gate.py — tests CONGELADOS de la etapa gate-nonecmp (opt-in `forbid_none_eq: true`):
si se exige, el gate falla cuando la función compara con None usando ==/!=. Default-off. Sin LLM."""
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
          "        self.assertEqual(f(1), True)\n\n"
          "if __name__ == '__main__':\n"
          "    unittest.main()\n")

CONTRACT = '''---
task: nonecmp-demo
intent: "Indicar si el valor no es None."
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
__FLAG__---

## Intent
Indicar si x no es None. Exito: pasa tests, budget y la política de comparación si se exige.

## Interface
- in: x. out: bool.

## Invariants
- f(1) is True.

## Examples
- f(1) -> True
- f(None) -> False

## Do / Don't
- DO: comparar con None. DON'T: estado global.

## Tests
test_x.py: oraculo independiente.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make(impl_src, forbid=False):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl_src, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    flag = "forbid_none_eq: true\n" if forbid else ""
    (d / "task.md").write_text(CONTRACT.replace("__FLAG__", flag), encoding="utf-8")
    return d / "task.md"


BAD = "def f(x):\n    return x != None\n"   # antipatrón
GOOD = "def f(x):\n    return x is not None\n"


class NoneCmpGate(unittest.TestCase):
    def test_eq_none_blocks_when_forbidden(self):
        t = _make(BAD, forbid=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-nonecmp")
            self.assertTrue(v.get("none_eq_lines"))
        finally:
            shutil.rmtree(t.parent)

    def test_is_passes_when_forbidden(self):
        t = _make(GOOD, forbid=True)
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)

    def test_optin_off_is_backcompat(self):
        t = _make(BAD, forbid=False)
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
