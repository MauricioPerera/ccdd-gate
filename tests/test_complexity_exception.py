"""test_complexity_exception.py — la excepción de complejidad (escape hatch humano)
SÓLO exime con firma Ed25519 válida de un revisor registrado. Sin LLM, sin red.

Cubre el fix de RB2:
  - firma simulada/inválida → NO exime (antes cualquiera escribía attestations.json).
  - firma Ed25519 válida de revisor registrado → SÍ exime.
  - reviewer no registrado, o sin reviewers.json → NO exime.
El hash firmado y el comparado es el MISMO: semantic_hash.get_semantic_hash (el que
usa request_human_attestation al crear la petición).
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
sys.path.insert(0, str(REPO))
import complexity_gate  # noqa: E402
import review_attestations  # noqa: E402
import semantic_hash  # noqa: E402
import ccdd  # noqa: E402  (lib upstream: sign/verify Ed25519 reutilizado)

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import (  # noqa: E402
    Encoding, PrivateFormat, PublicFormat, NoEncryption)

CODE = "def f(x):\n    return x\n"


def _keypair():
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return priv_hex, pub_hex


class SignException(unittest.TestCase):
    def test_signs_real_ed25519_not_literal(self):
        priv_hex, pub_hex = _keypair()
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        entry = review_attestations.sign_exception("mauricio", h, priv_hex)
        self.assertEqual(entry["reviewer"], "mauricio")
        self.assertEqual(entry["content_sha256"], h)
        self.assertNotEqual(entry["signature"], "simulated-signature-for-complexity")
        # verifica contra la clave pública (msg = EXEMPTION_SLOT:h)
        self.assertTrue(ccdd.verify_attestation(
            pub_hex, review_attestations.EXEMPTION_SLOT, h, entry["signature"]))


class IsExempt(unittest.TestCase):
    def _contract_dir(self, reviewers, attest):
        d = Path(tempfile.mkdtemp())
        if reviewers is not None:
            (d / "reviewers.json").write_text(json.dumps(reviewers), encoding="utf-8")
        (d / "attestations.json").write_text(json.dumps(attest), encoding="utf-8")
        return d

    def test_valid_signature_of_registered_reviewer_exempts(self):
        priv_hex, pub_hex = _keypair()
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        entry = review_attestations.sign_exception("mauricio", h, priv_hex)
        d = self._contract_dir({"mauricio": pub_hex}, {"complexity_exception": [entry]})
        try:
            exempt, eh = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertTrue(exempt, "firma válida de revisor registrado debe eximir")
            self.assertEqual(eh, h)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_simulated_signature_does_not_exempt(self):
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        entry = {"reviewer": "mauricio", "content_sha256": h,
                 "signature": "simulated-signature-for-complexity"}
        d = self._contract_dir({"mauricio": "deadbeef"}, {"complexity_exception": [entry]})
        try:
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertFalse(exempt, "firma simulada NO debe eximir")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_wrong_hash_does_not_exempt(self):
        priv_hex, pub_hex = _keypair()
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        # firma sobre otro hash: content_sha256 coincide con h, pero la firma cubre otro
        entry = review_attestations.sign_exception("mauricio", "0" * 64, priv_hex)
        entry["content_sha256"] = h  # mismatch: la firma NO cubre este hash
        d = self._contract_dir({"mauricio": pub_hex}, {"complexity_exception": [entry]})
        try:
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertFalse(exempt, "firma sobre otro hash NO debe eximir")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unregistered_reviewer_does_not_exempt(self):
        priv_hex, pub_hex = _keypair()
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        entry = review_attestations.sign_exception("intruder", h, priv_hex)
        d = self._contract_dir({"mauricio": "00"}, {"complexity_exception": [entry]})
        try:
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertFalse(exempt, "reviewer no registrado NO debe eximir")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_reviewers_json_does_not_exempt(self):
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        d = self._contract_dir(None, {"complexity_exception": [
            {"reviewer": "x", "content_sha256": h, "signature": "deadbeef"}]})
        try:
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertFalse(exempt, "sin reviewers.json no hay firma verificable")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_slot_must_match(self):
        # firma sobre un slot distinto al que verifica el gate → no verifica
        priv_hex, pub_hex = _keypair()
        h = semantic_hash.get_semantic_hash(CODE, ".py")
        sig = ccdd.sign_attestation(priv_hex, "other-slot", h)
        entry = {"reviewer": "mauricio", "content_sha256": h, "signature": sig}
        d = self._contract_dir({"mauricio": pub_hex}, {"complexity_exception": [entry]})
        try:
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=d)
            self.assertFalse(exempt, "firma sobre otro slot NO debe eximir")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()