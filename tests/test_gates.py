"""test_gates.py — tests CONGELADOS del núcleo determinista (tc_lint + task_gate). Sin LLM.
El gate que juzga a los demás se autojuzga: veredictos reproducibles corrida a corrida.

PASS usa el sandbox estable (examples/sandbox/*). Los casos FAIL/INVALID construyen su propia
variante en un tempdir (budget apretado, impl rota, aprobación faltante) — sin tocar fixtures.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import tc_lint    # noqa: E402
import task_gate  # noqa: E402

SANDBOX = REPO / "examples" / "sandbox"
TASK = SANDBOX / "task.md"
TEST = SANDBOX / "test_decode_instruction.py"
GOOD_IMPL = SANDBOX / "disassembler.py"

BROKEN_CONTRACT = """---
task: malo
intent: hace una cosa y además otra
budget: { cyclomatic_max: 999 }
---
# cuerpo sin secciones
"""


def _variant(budget_repl=None, impl_text=None):
    """Copia el sandbox a un tempdir y opcionalmente aprieta el budget o rompe la impl.
    Devuelve la ruta del task.md en el tempdir (el caller borra el dir)."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(TEST, d / "test_decode_instruction.py")
    (d / "disassembler.py").write_text(
        impl_text if impl_text is not None else GOOD_IMPL.read_text(encoding="utf-8"), encoding="utf-8")
    task = TASK.read_text(encoding="utf-8")
    if budget_repl:
        task = task.replace(*budget_repl)
    (d / "task.md").write_text(task, encoding="utf-8")
    return d / "task.md"


BAD_IMPL = '''OPCODES = {0x00: ("NOP", 1), 0x06: ("LD B, ${:02X}", 2),
           0x3E: ("LD A, ${:02X}", 2), 0xC3: ("JP ${:04X}", 3)}


def decode_instruction(rom, pc):
    opcode = rom[pc]
    if opcode not in OPCODES:
        return f"{opcode:02X}", f"DB ${opcode:02X} (Desconocido / Datos)", 2  # rompe invariante
    fmt, size = OPCODES[opcode]
    hexb = " ".join(f"{rom[pc + i]:02X}" for i in range(size) if pc + i < len(rom))
    operands = rom[pc + 1:pc + size]
    val = int.from_bytes(operands, "little") if operands else None
    return hexb, (fmt.format(val) if val is not None else fmt), size
'''


class TestTcLint(unittest.TestCase):
    def test_valid_contract_no_errors(self):
        findings = tc_lint.lint(TASK)
        self.assertEqual([f for f in findings if f["level"] == "error"], [])

    def test_broken_contract_flags_rules(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = d / "task.md"
            p.write_text(BROKEN_CONTRACT, encoding="utf-8")
            rules = {f["rule"] for f in tc_lint.lint(p) if f["level"] == "error"}
        finally:
            shutil.rmtree(d, ignore_errors=True)
        for expected in ("tc-required", "tc-intent-atomic", "tc-budget-sane", "tc-sections", "tc-stop-rule"):
            self.assertIn(expected, rules)


class TestTaskGate(unittest.TestCase):
    def test_pass_on_sandbox(self):
        v = task_gate.gate(str(TASK))
        self.assertEqual(v["verdict"], "PASS")

    def test_fail_gate1_over_budget(self):
        p = _variant(budget_repl=("cyclomatic_max: 8", "cyclomatic_max: 1"))
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "gate1-complexity")

    def test_fail_gate2_broken_impl(self):
        p = _variant(impl_text=BAD_IMPL)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "gate2-tests")

    def test_invalid_unapproved_tests(self):
        p = _variant(budget_repl=("spec_version:", "require_test_approval: true\nspec_version:"))
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "INVALID")
        self.assertEqual(v["stage"], "test-approval")


if __name__ == "__main__":
    unittest.main()
