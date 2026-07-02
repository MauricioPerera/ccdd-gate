#!/usr/bin/env python3
"""review_attestations.py — CLI para que el Arquitecto revise peticiones del agente.

Revisa los JSONs en pending_attestations/, y por cada uno muestra el código,
el motivo, y permite aprobarlo (firmándolo con Ed25519 y metiéndolo en
attestations.json) o rechazarlo (eliminando la petición).

Aprobar exige la clave PRIVADA Ed25519 del revisor y firma `EXEMPTION_SLOT:hash`
con ccdd.sign_attestation (misma mecánica que las atestaciones de política R6).
Se guarda la firma real (hex), NO un literal — una firma simulada NO exime el gate.

Clave del revisor (headless): --key <ruta-a-privada> | env CCDD_REVIEWER_KEY (ruta)
  | env CCDD_REVIEWER_KEY_HEX (hex). Sin clave no se aprueba (no se simula firma).
Reviewer: --reviewer <id> | env CCDD_REVIEWER | se pide por input interactivo.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent / "contracts"

EXEMPTION_SLOT = "complexity_exception"  # debe coincidir con complexity_gate.EXEMPTION_SLOT


def _cli_arg(name):
    """Valor de `--name` (path/str) en sys.argv, o None."""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def sign_exception(reviewer, content_hash, priv_hex):
    """Firma la excepción (Ed25519) sobre EXEMPTION_SLOT:content_hash y devuelve la
    entrada a guardar en attestations.json. Reusa ccdd.sign_attestation (R6)."""
    sys.path.insert(0, str(HERE.parent))
    import ccdd
    sig = ccdd.sign_attestation(priv_hex, EXEMPTION_SLOT, content_hash)
    return {"reviewer": reviewer, "content_sha256": content_hash, "signature": sig}


def _read_priv_hex():
    """Clave privada Ed25519 (hex) del revisor desde --key <path>, env CCDD_REVIEWER_KEY
    (path) o env CCDD_REVIEWER_KEY_HEX (hex). None si no se provee."""
    key_path = _cli_arg("--key") or os.environ.get("CCDD_REVIEWER_KEY")
    if key_path and Path(key_path).exists():
        return Path(key_path).read_text(encoding="utf-8").strip()
    return (os.environ.get("CCDD_REVIEWER_KEY_HEX") or "").strip() or None


def main():
    agent = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "complexity-agent"
    pending_dir = CONTRACTS / agent / "pending_attestations"
    attest_path = CONTRACTS / agent / "attestations.json"

    if not pending_dir.exists() or not os.listdir(pending_dir):
        print(f"No hay atestaciones pendientes para {agent}.")
        return 0

    if attest_path.exists():
        attest = json.loads(attest_path.read_text(encoding="utf-8"))
    else:
        attest = {}

    if "complexity_exception" not in attest:
        attest["complexity_exception"] = []
    elif isinstance(attest["complexity_exception"], dict):
        attest["complexity_exception"] = [attest["complexity_exception"]]

    for p in pending_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error al leer o parsear {p.name}: {e}. Saltando...", file=sys.stderr)
            continue
        print("\n" + "="*60)
        print(f"ARCHIVO: {data.get('filename')}")
        print(f"HASH:    {data.get('hash')}")
        print(f"MOTIVO:  {data.get('reason')}")
        print("-"*60)
        print(data.get("code", ""))
        print("="*60)

        ans = input("¿Aprobar esta excepción de complejidad? [y/N]: ").strip().lower()
        if ans != "y":
            print("Rechazado.")
            p.unlink()
            continue
        rev = _cli_arg("--reviewer") or os.environ.get("CCDD_REVIEWER") \
            or input("Tu ID de reviewer (ej. mauricio): ").strip()
        priv_hex = _read_priv_hex()
        if not priv_hex:
            print("Falta la clave privada Ed25519 del revisor (--key <path> | CCDD_REVIEWER_KEY | "
                  "CCDD_REVIEWER_KEY_HEX). NO se aprueba: sin firma real no se exime el gate.",
                  file=sys.stderr)
            continue
        attest["complexity_exception"].append(sign_exception(rev, data["hash"], priv_hex))
        print("Aprobado y firmado (Ed25519), añadido a attestations.json")
        p.unlink()

    attest_path.write_text(json.dumps(attest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nProceso finalizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())