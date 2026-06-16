"""test_tc_lint_rules.py — una regla de tc_lint por caso, AISLADA. Parte del sandbox válido
(0 errores) y muta una sola cosa por vez, de modo que cada regla se verifica sola y no solo
dentro de un contrato roto combinado. Determinista, sin LLM."""
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import tc_lint  # noqa: E402

SANDBOX = REPO / "examples" / "sandbox"


def fresh_task():
    d = Path(tempfile.mkdtemp())
    shutil.copy(SANDBOX / "task.md", d / "task.md")
    shutil.copy(SANDBOX / "test_decode_instruction.py", d / "test_decode_instruction.py")
    return d, d / "task.md"


def rewrite(task_path, fm_fn=None, body_fn=None):
    text = task_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    fm, body = yaml.safe_load(m.group(1)), m.group(2)
    if fm_fn:
        fm_fn(fm)
    if body_fn:
        body = body_fn(body)
    out = "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip() + "\n---\n" + body
    task_path.write_text(out, encoding="utf-8")


def rules(task_path, level):
    return {f["rule"] for f in tc_lint.lint(str(task_path)) if f["level"] == level}


class TestTcLintPerRule(unittest.TestCase):
    def _case(self, level, expect_rule, fm_fn=None, body_fn=None):
        d, task = fresh_task()
        try:
            self.assertNotIn(expect_rule, rules(task, level))  # baseline limpio: la regla NO está
            rewrite(task, fm_fn, body_fn)
            self.assertIn(expect_rule, rules(task, level))     # tras la mutación: la regla dispara
        finally:
            shutil.rmtree(d, ignore_errors=True)

    # --- errores ---
    def test_required(self):
        self._case("error", "tc-required", fm_fn=lambda fm: fm.pop("target"))

    def test_intent_atomic(self):
        self._case("error", "tc-intent-atomic", fm_fn=lambda fm: fm.update(intent="decodifica y valida la instrucción"))

    def test_signature_unparseable(self):
        self._case("error", "tc-signature-valid", fm_fn=lambda fm: fm.update(signature="esto no es un def"))

    def test_budget_over_global(self):
        self._case("error", "tc-budget-sane", fm_fn=lambda fm: fm["budget"].update(cyclomatic_max=999))

    def test_tests_missing(self):
        self._case("error", "tc-tests-frozen", fm_fn=lambda fm: fm.update(tests="no_existe.py"))

    def test_section_missing(self):
        self._case("error", "tc-sections", body_fn=lambda b: b.replace("## Invariants", "## QuitadaInvariants"))

    def test_stop_rule(self):
        self._case("error", "tc-stop-rule", body_fn=lambda b: b.replace("PARAR", "DETENER"))

    # --- warnings ---
    def test_no_algorithm(self):
        self._case("warn", "tc-no-algorithm",
                   body_fn=lambda b: b.replace("## Intent\n", "## Intent\n1. primero esto\n2. luego lo otro\n", 1))

    def test_deps_declared(self):
        def m(fm):
            fm.pop("deps_allowed", None)
            fm.pop("forbids", None)
        self._case("warn", "tc-deps-declared", fm_fn=m)


if __name__ == "__main__":
    unittest.main()
