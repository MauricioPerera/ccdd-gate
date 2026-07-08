"""test_complexity_gate_exemption.py — la excepción de complejidad exige firma Ed25519
VÁLIDA de un reviewer registrado en reviewers.json, no un content_sha256 que matchea nada
más. Sin LLM, determinista (claves generadas en runtime, sin red, sin mocks de crypto)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNERS = REPO / "runners"
sys.path.insert(0, str(RUNNERS))
sys.path.insert(0, str(REPO))
import complexity_gate  # noqa: E402
import ccdd              # noqa: E402
import semantic_hash     # noqa: E402

CODE = "def f(a):\n    return a\n"


def _keypair():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption)
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    pub_hex = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return priv_hex, pub_hex


def _write_registry(cdir, reviewers, exceptions):
    (cdir / "reviewers.json").write_text(json.dumps(reviewers), encoding="utf-8")
    (cdir / "attestations.json").write_text(
        json.dumps({"complexity_exception": exceptions}), encoding="utf-8")


class TestComplexityExemption(unittest.TestCase):
    def setUp(self):
        self.h = semantic_hash.get_semantic_hash(CODE, ".py")

    def test_valid_signature_from_registered_reviewer_exempts(self):
        priv_hex, pub_hex = _keypair()
        sig = ccdd.sign_attestation(priv_hex, complexity_gate.SIGNATURE_SLOT_ID, self.h)
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d)
            _write_registry(cdir, {"alice": pub_hex},
                            [{"reviewer": "alice", "content_sha256": self.h, "signature": sig}])
            exempt, h = complexity_gate._is_exempt(CODE, ".py", contract_dir=cdir)
        self.assertTrue(exempt)
        self.assertEqual(h, self.h)

    def test_signature_over_different_content_does_not_exempt(self):
        """La firma es Ed25519 válida... pero para OTRO hash. No debe eximir este código."""
        priv_hex, pub_hex = _keypair()
        other_hash = semantic_hash.get_semantic_hash("def g():\n    pass\n", ".py")
        sig = ccdd.sign_attestation(priv_hex, complexity_gate.SIGNATURE_SLOT_ID, other_hash)
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d)
            _write_registry(cdir, {"alice": pub_hex},
                            [{"reviewer": "alice", "content_sha256": self.h, "signature": sig}])
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=cdir)
        self.assertFalse(exempt)

    def test_unregistered_reviewer_does_not_exempt(self):
        """Firma Ed25519 real y válida, pero el reviewer no está en reviewers.json."""
        priv_hex, _pub_hex = _keypair()
        sig = ccdd.sign_attestation(priv_hex, complexity_gate.SIGNATURE_SLOT_ID, self.h)
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d)
            _write_registry(cdir, {},
                            [{"reviewer": "mallory", "content_sha256": self.h, "signature": sig}])
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=cdir)
        self.assertFalse(exempt)

    def test_forged_signature_does_not_exempt(self):
        """content_sha256 matchea y el reviewer esta registrado, pero la firma es basura:
        exactamente lo que el viejo placeholder 'simulated-signature-for-complexity'
        habria producido antes de este fix."""
        _priv_hex, pub_hex = _keypair()
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d)
            _write_registry(cdir, {"alice": pub_hex},
                            [{"reviewer": "alice", "content_sha256": self.h,
                              "signature": "simulated-signature-for-complexity"}])
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=cdir)
        self.assertFalse(exempt)

    def test_no_reviewers_file_never_exempts(self):
        priv_hex, _pub_hex = _keypair()
        sig = ccdd.sign_attestation(priv_hex, complexity_gate.SIGNATURE_SLOT_ID, self.h)
        with tempfile.TemporaryDirectory() as d:
            cdir = Path(d)
            (cdir / "attestations.json").write_text(json.dumps(
                {"complexity_exception": [{"reviewer": "alice", "content_sha256": self.h,
                                           "signature": sig}]}), encoding="utf-8")
            exempt, _ = complexity_gate._is_exempt(CODE, ".py", contract_dir=cdir)
        self.assertFalse(exempt)

    def test_no_attestations_file_never_exempts(self):
        with tempfile.TemporaryDirectory() as d:
            exempt, h = complexity_gate._is_exempt(CODE, ".py", contract_dir=Path(d))
        self.assertFalse(exempt)
        self.assertEqual(h, self.h)


if __name__ == "__main__":
    unittest.main()
