"""test_attest_hash_consistency.py — RE1: el hash que `cmd_attest` guarda como
`content_sha256` debe ser el MISMO que la verificación R6/R7 compara.

Bug latente: `_attest_target_hash` firmaba con SHA-256 crudo del `read_text`,
mientras R6 verifica con `semantic_hash.get_semantic_hash(text, suffix)`.
Para `.txt`/`.json` el hash semántico cae al fallback crudo -> coinciden (no-op).
Para un slot estático `.py` (permitido por el schema) el crudo != semántico
(`ast.dump`), así que una atestación legitima de un revisor registrado era
RECHAZADA por R6. Este test clava la invariante no-op Y el round-trip `.py`.

Reutiliza la maquinaria de test_l2_governance (CLI por subprocess, como CI)."""
import hashlib
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

sys.path.insert(0, str(REPO))
import ccdd  # noqa: E402  (modulo del repo, para llamar _attest_target_hash directo)
from runners import semantic_hash  # noqa: E402


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


def has(items, sub):
    return any(sub in x for x in items)


def add_py_slot(contract_dir, slot_id="pycrit", fname="pycrit.py"):
    """Agrega un slot estático `.py` crítico (compaction: none) al contrato."""
    py_text = "def f(x):\n    return x + 1\n"
    (contract_dir / fname).write_text(py_text, encoding="utf-8")

    def fn(contract):
        contract["slots"].append({
            "id": slot_id,
            "priority": 1,
            "source": {"type": "static", "path": fname, "sign": True},
            "compaction": "none",
            "min_tokens": 10,
            "review_quorum": 1,
        })
    data = yaml.safe_load((contract_dir / "context.yaml").read_text(encoding="utf-8"))
    fn(data["contract"])
    (contract_dir / "context.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return py_text


class TestAttestHashNoOp(unittest.TestCase):
    """(a) Para `.txt`/`.json` el hash debe ser BYTE-IDENTICO al crudo previo
    (`sha256(read_text)`), para no invalidar atestaciones existentes."""

    def test_txt_slot_is_raw_sha256(self):
        d, base, _ = make_pair()
        try:
            text = (base / "system.txt").read_text(encoding="utf-8")
            expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
            h, rc = ccdd._attest_target_hash(base, "system")
            self.assertIsNone(rc)
            self.assertEqual(h, expected)
            # además coincide con el hash semántico (fallback crudo) que usa R6
            self.assertEqual(h, semantic_hash.get_semantic_hash(text, ".txt"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_reviewers_json_is_raw_sha256(self):
        d, base, _ = make_pair()
        try:
            rp = base / "reviewers.json"
            rp.write_text(json.dumps({"alice": "00"}, indent=2) + "\n", encoding="utf-8")
            text = rp.read_text(encoding="utf-8")
            expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
            h, rc = ccdd._attest_target_hash(base, "__reviewers__")
            self.assertIsNone(rc)
            self.assertEqual(h, expected)
            self.assertEqual(h, semantic_hash.get_semantic_hash(text, ".json"))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_py_slot_matches_semantic_hash(self):
        """Un slot `.py` se hashea con ast.dump (semántico), no con el crudo:
        el valor que `cmd_attest` guarda == el que R6 usa para verificar."""
        d, base, _ = make_pair()
        try:
            add_py_slot(base)
            text = (base / "pycrit.py").read_text(encoding="utf-8")
            h, rc = ccdd._attest_target_hash(base, "pycrit")
            self.assertIsNone(rc)
            self.assertEqual(h, semantic_hash.get_semantic_hash(text, ".py"))
            self.assertNotEqual(h, hashlib.sha256(text.encode("utf-8")).hexdigest())
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestAttestPyRoundTrip(unittest.TestCase):
    """(b) Round-trip .py end-to-end: cambio de contenido de un slot `.py`
    crítico -> bloqueado sin atestación -> `cmd_attest` firma -> R6 ACEPTA
    (signers suficientes). Antes del fix esto fallaba por mismatch crudo/semántico.
    """

    def test_py_critical_change_blocked_then_attested(self):
        d, base, head = make_pair()
        try:
            # mismo slot .py en base y head (contenido inicial idéntico)
            add_py_slot(base)
            add_py_slot(head)

            key = d / "alice.key"
            kg = run_ccdd("keygen", str(base), "--reviewer", "alice", "--key-out", str(key))
            self.assertEqual(kg.returncode, 0, kg.stderr)
            shutil.copy(base / "reviewers.json", head / "reviewers.json")  # mismo registro -> no R7

            # cambio de contenido del slot .py (semánticamente distinto)
            (head / "pycrit.py").write_text(
                "def f(x):\n    return x + 2\n", encoding="utf-8")

            code, rep = diff(base, head)  # cambio crítico SIN atestación -> bloquea
            self.assertEqual(code, 1, rep)
            self.assertTrue(has(rep["regressions"], "sin atestación"), rep.get("regressions"))

            at = run_ccdd("attest", str(head), "pycrit", "--reviewer", "alice",
                          "--key", str(key), "--note", "revisión .py")
            self.assertEqual(at.returncode, 0, at.stderr)

            code, rep = diff(base, head)  # atestada con firma válida -> pasa
            self.assertEqual(code, 0, rep)
            self.assertTrue(rep["passed"], rep)
            self.assertTrue(has(rep["changes"], "ATESTADA"), rep.get("changes"))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()