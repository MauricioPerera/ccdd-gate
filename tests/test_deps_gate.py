"""test_deps_gate.py — tests CONGELADOS de la etapa gate-deps de task_gate (enforcement OPT-IN de
deps_allowed). Sin LLM. Define el contrato que la integración debe cumplir:

  - enforce_deps: true  + import de tercero NO permitido  -> FAIL, stage 'gate-deps'
  - enforce_deps: true  + ese tercero en deps_allowed     -> PASS (no lo bloquea)
  - enforce_deps ausente (default)                        -> la etapa NO corre (back-compat): PASS

Usa `yaml` (pyyaml, dependencia del repo) como import de tercero: es importable (el test del target
no rompe) y NO es stdlib (unauthorized_imports lo marca)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import task_gate  # noqa: E402

IMPL = "import yaml\n\n\ndef f(x):\n    return x\n"
TEST_X = ("import unittest\n"
          "from impl import f\n\n"
          "class T(unittest.TestCase):\n"
          "    def test_f(self):\n"
          "        self.assertEqual(f(1), 1)\n\n"
          "if __name__ == '__main__':\n"
          "    unittest.main()\n")

CONTRACT = '''---
task: deps-demo
intent: "Devolver el valor recibido."
target: impl.py
signature: "def f(x)"
test_command: "python -m unittest test_x"
test_cwd: "."
budget: {{ cyclomatic_max: 3, nesting_max: 1, params_max: 1, lines_max: 10 }}
deps_allowed: {deps_allowed}
{enforce}tests: test_x.py
forbids: ["estado global"]
spec_version: "0.1"
require_test_approval: false
---

## Intent
Devolver x. Exito: pasa los tests, respeta el budget y la politica de deps.

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


def _make(deps_allowed="[]", enforce=False):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(IMPL, encoding="utf-8")
    (d / "test_x.py").write_text(TEST_X, encoding="utf-8")
    enforce_line = "enforce_deps: true\n" if enforce else ""
    (d / "task.md").write_text(CONTRACT.format(deps_allowed=deps_allowed, enforce=enforce_line), encoding="utf-8")
    return d / "task.md"


class DepsGate(unittest.TestCase):
    def test_enforce_blocks_unauthorized(self):
        t = _make(deps_allowed="[]", enforce=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-deps")
            self.assertIn("yaml", v.get("unauthorized", []))
        finally:
            shutil.rmtree(t.parent)

    def test_enforce_passes_when_allowed(self):
        t = _make(deps_allowed='["yaml"]', enforce=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent)

    def test_optin_default_off_is_backcompat(self):
        t = _make(deps_allowed="[]", enforce=False)  # sin enforce_deps: la etapa no corre
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent)


if __name__ == "__main__":
    unittest.main()
