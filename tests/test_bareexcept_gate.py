"""test_bareexcept_gate.py — tests CONGELADOS de la etapa gate-bareexcept (opt-in
`forbid_bare_except: true`): si se exige, el gate falla cuando la función tiene `except:` desnudo.
Default-off. Sin LLM."""
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
          "        self.assertEqual(f(), 1)\n\n"
          "if __name__ == '__main__':\n"
          "    unittest.main()\n")

CONTRACT = '''---
task: bareexcept-demo
intent: "Devolver uno."
target: impl.py
signature: "def f()"
test_command: "python -m unittest test_x"
test_cwd: "."
budget: { cyclomatic_max: 4, nesting_max: 2, params_max: 0, lines_max: 12 }
deps_allowed: []
forbids: ["estado global"]
tests: test_x.py
spec_version: "0.1"
__FLAG__---

## Intent
Devolver 1. Exito: pasa tests, budget y la política de except si se exige.

## Interface
- in: nada. out: 1.

## Invariants
- f() == 1.

## Examples
- f() -> 1
- f() -> 1 (idempotente)

## Do / Don't
- DO: devolver 1. DON'T: estado global.

## Tests
test_x.py: oraculo independiente.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make(impl_src, forbid=False):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(impl_src, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    flag = "forbid_bare_except: true\n" if forbid else ""
    (d / "task.md").write_text(CONTRACT.replace("__FLAG__", flag), encoding="utf-8")
    return d / "task.md"


BARE = "def f():\n    try:\n        return 1\n    except:\n        return 1\n"
TYPED = "def f():\n    try:\n        return 1\n    except Exception:\n        return 1\n"


class BareExceptGate(unittest.TestCase):
    def test_bare_blocks_when_forbidden(self):
        t = _make(BARE, forbid=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-bareexcept")
            self.assertTrue(v.get("bare_except_lines"))
        finally:
            shutil.rmtree(t.parent)

    def test_typed_passes_when_forbidden(self):
        t = _make(TYPED, forbid=True)
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)

    def test_optin_off_is_backcompat(self):
        t = _make(BARE, forbid=False)
        try:
            self.assertEqual(task_gate.gate(str(t))["verdict"], "PASS")
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
