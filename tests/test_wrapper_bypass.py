"""test_wrapper_bypass.py — tests CONGELADOS del gate-wrapper (anti-bypass de delegación trivial).

El gate mide SOLO la función target. Sin este check, un implementador deja el target como un
pass-through trivial (`def f(n): return g(n)`) y esconde toda la complejidad en un sibling de
módulo `g` del MISMO archivo que no es target de ningún contrato: `f` pasa el budget midiendo la
cáscara y `g` (la lógica real) es invisible al gate. gate-wrapper (default-ON, detección estrecha)
cae en la cadena JUSTO antes de _gate_complexity y mide al sibling; si excede el budget -> INVALID.

Cobertura (definición de hecho):
  (a) delegación trivial a un sibling de 15 ifs sobre budget  -> INVALID/gate-wrapper (hoy PASS).
  (b) control: el sibling está DENTRO del budget              -> PASS (wrapper no aplica).
  (c) control: el target hace trabajo real y además llama a g -> NO gate-wrapper (va a complexity).
  (d) control: delegación a algo importado/externo (no sibling) -> NO gate-wrapper (va a complexity).
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import task_gate  # noqa: E402

# 15 ifs planos -> cyclomatic 16, nesting 1, params 1, lines ~17. Siempre sobre budget apretado.
_G_15 = "def g(n):\n" + "".join(f"    if n == {i}:\n        return {i}\n" for i in range(1, 16)) + "    return 0\n"

_CONTRACT = """---
task: wrapper-bypass
intent: "Devolver un entero delegando."
target: target.py
signature: "def f(n: int) -> int"
tests: test_f.py
test_command: "python test_f.py"
budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 1, lines_max: 12 }
require_test_approval: false
spec_version: "0.1"
---

## Intent
Devolver un entero a partir de n.

## Interface
```
in:  n: int
out: int
error: no lanza
```

## Invariants
- Resultado int.

## Examples
- f(0) -> 0
- f(1) -> 1

## Do / Don't
- DO: delegar en g.
- DON'T: no complejidad en f.

## Tests
test_f.py con casos fijos.

## Constraints
- PARAR y reportar si no se puede cumplir sin violar la interfaz. Sin workarounds silenciosos.
"""


def _build(impl_text, test_text):
    """Tempdir con target.py + test_f.py + task.md válido (approval off, tests que pasan).
    Devuelve (dir, task_path); el caller borra el dir."""
    d = Path(tempfile.mkdtemp())
    (d / "target.py").write_text(impl_text, encoding="utf-8")
    (d / "test_f.py").write_text(test_text, encoding="utf-8")
    (d / "task.md").write_text(_CONTRACT, encoding="utf-8")
    return d, d / "task.md"


class TestGateWrapperBypass(unittest.TestCase):
    def test_a_trivial_delegator_to_over_budget_sibling_is_invalid(self):
        # HOY (sin gate-wrapper) esto daría PASS: f (cyc 1) mide la cáscara; g (cyc 16) es invisible.
        impl = _G_15 + "\n\ndef f(n):\n    return g(n)\n"
        test = "import target\nassert target.f(0) == 0\nassert target.f(7) == 7\nassert target.f(15) == 15\nassert target.f(99) == 0\n"
        d, p = _build(impl, test)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(v["verdict"], "INVALID", v)
        self.assertEqual(v["stage"], "gate-wrapper", v)
        self.assertEqual(v["sibling"], "g", v)
        # el detail cita al sibling y al budget; las métricas del sibling se reportan para auditar.
        self.assertIn("g", v["detail"])
        self.assertGreater(v["sibling_metrics"]["cyclomatic"], v["budget"]["cyclomatic_max"])

    def test_b_sibling_within_budget_passes(self):
        # g (cyc 1) dentro del budget: wrapper no aplica -> complexity mide f (cyc 1) -> PASS.
        impl = "def g(n):\n    return n\n\n\ndef f(n):\n    return g(n)\n"
        test = "import target\nassert target.f(0) == 0\nassert target.f(7) == 7\n"
        d, p = _build(impl, test)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertEqual(v["verdict"], "PASS", v)
        self.assertEqual(v["stage"], "all", v)

    def test_c_target_does_real_work_proceeds_to_complexity(self):
        # f hace trabajo real (un if) además de llamar a g: NO es pass-through trivial -> wrapper
        # cede. complexity mide f (cyc 2) dentro del budget -> PASS. g (complejo) sigue invisible
        # (el hueco de depth-1 es intencional); lo que se verifica aquí es que wrapper NO dispara.
        impl = _G_15 + "\n\ndef f(n):\n    if n < 0:\n        return -1\n    return g(n)\n"
        test = "import target\nassert target.f(0) == 0\nassert target.f(7) == 7\nassert target.f(-1) == -1\n"
        d, p = _build(impl, test)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertNotEqual(v["stage"], "gate-wrapper", v)
        self.assertEqual(v["verdict"], "PASS", v)
        self.assertEqual(v["stage"], "all", v)

    def test_d_delegation_to_imported_not_sibling_proceeds_to_complexity(self):
        # sqrt es importado (no def a nivel de módulo): NO es sibling -> wrapper no aplica.
        # complexity mide f (cyc 1) -> PASS.
        impl = "from math import sqrt\n\n\ndef f(n):\n    return sqrt(n)\n"
        test = "import target\nassert target.f(9) == 3\nassert target.f(16) == 4\n"
        d, p = _build(impl, test)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertNotEqual(v["stage"], "gate-wrapper", v)
        self.assertEqual(v["verdict"], "PASS", v)
        self.assertEqual(v["stage"], "all", v)


if __name__ == "__main__":
    unittest.main()