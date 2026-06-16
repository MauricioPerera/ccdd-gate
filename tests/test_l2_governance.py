"""test_l2_governance.py — tests del gate L2 de ccdd.py (diff R1-R9) + atestación Ed25519 REAL.

CLI end-to-end por subprocess, como lo correría CI. Veredictos deterministas; las claves se
generan frescas por test (la verificación de firma es determinista dado el par). Cubre los
regresores que bloquean el merge y el ciclo de gobernanza completo: cambio de política crítica
BLOQUEADO sin atestación -> keygen -> attest firmado -> PASA.

Requiere `cryptography` (keygen/attest)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CCDD = REPO / "ccdd.py"
BASE_CONTRACT = REPO / "contracts" / "task-author-agent"


def run_ccdd(*args):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(CCDD), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


def make_pair():
    d = Path(tempfile.mkdtemp())
    base, head = d / "base", d / "head"
    shutil.copytree(BASE_CONTRACT, base)
    shutil.copytree(BASE_CONTRACT, head)
    return d, base, head


def diff(base, head):
    r = run_ccdd("diff", str(base), str(head), "--json")
    rep = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {"_out": r.stdout, "_err": r.stderr}
    return r.returncode, rep


def edit_contract(path, fn):
    data = yaml.safe_load((path / "context.yaml").read_text(encoding="utf-8"))
    fn(data["contract"])
    (path / "context.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def has(items, sub):
    return any(sub in x for x in items)


class TestL2Clean(unittest.TestCase):
    def test_identical_passes(self):
        d, base, head = make_pair()
        try:
            code, rep = diff(base, head)
            self.assertEqual(code, 0, rep)
            self.assertTrue(rep["passed"], rep)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestL2Regressions(unittest.TestCase):
    """Cada mutación de HEAD debe BLOQUEAR (exit 1 + regresión esperada)."""

    def _expect_block(self, mutate, sub):
        d, base, head = make_pair()
        try:
            edit_contract(head, mutate)
            code, rep = diff(base, head)
            self.assertEqual(code, 1, rep)
            self.assertFalse(rep["passed"], rep)
            self.assertTrue(has(rep["regressions"], sub), rep.get("regressions"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_r9_guardrail_removed(self):
        self._expect_block(
            lambda c: c.__setitem__("guardrails", [g for g in c["guardrails"] if g["id"] != "no-secrets"]),
            "eliminado")

    def test_r9_guardrail_weakened(self):
        def m(c):
            for g in c["guardrails"]:
                if g["id"] == "no-secrets":
                    g["on_fail"] = "warn"
        self._expect_block(m, "debilitado")

    def test_r8_quorum_lowered(self):
        def m(c):
            for s in c["slots"]:
                if s["id"] == "thresholds":
                    s["review_quorum"] = 1
        self._expect_block(m, "review_quorum")

    def test_r4_signed_slot_loses_sign(self):
        def m(c):
            for s in c["slots"]:
                if s["id"] == "system":
                    s["source"]["sign"] = False
        self._expect_block(m, "perdió la firma")


class TestL2Attestation(unittest.TestCase):
    """Ciclo de gobernanza R6 con Ed25519 real: cambio crítico bloqueado -> firmado -> PASA."""

    def test_content_change_blocked_then_attested(self):
        d, base, head = make_pair()
        try:
            key = d / "alice.key"
            kg = run_ccdd("keygen", str(base), "--reviewer", "alice", "--key-out", str(key))
            self.assertEqual(kg.returncode, 0, kg.stderr)
            shutil.copy(base / "reviewers.json", head / "reviewers.json")  # mismo registro -> no dispara R7

            sysf = head / "system.txt"
            sysf.write_text(sysf.read_text(encoding="utf-8") + "\nNueva línea de política.\n", encoding="utf-8")

            code, rep = diff(base, head)  # cambio crítico SIN atestación -> bloquea
            self.assertEqual(code, 1, rep)
            self.assertTrue(has(rep["regressions"], "sin atestación"), rep.get("regressions"))

            at = run_ccdd("attest", str(head), "system", "--reviewer", "alice", "--key", str(key))
            self.assertEqual(at.returncode, 0, at.stderr)

            code, rep = diff(base, head)  # ahora atestada con firma válida -> pasa
            self.assertEqual(code, 0, rep)
            self.assertTrue(rep["passed"], rep)
            self.assertTrue(has(rep["changes"], "ATESTADA"), rep.get("changes"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
