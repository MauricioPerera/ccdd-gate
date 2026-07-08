#!/usr/bin/env python3
"""review_attestations.py — CLI para que el Arquitecto revise peticiones del agente.

Revisa los JSONs en pending_attestations/, y por cada uno muestra el código,
el motivo, y permite aprobarlo (firmando con Ed25519 real vía ccdd.sign_attestation
y metiéndolo en attestations.json) o rechazarlo (eliminando la petición).

Requiere que el reviewer ya esté registrado en contracts/<agent>/reviewers.json
(clave pública), generado con: python ccdd.py keygen contracts/<agent>
--reviewer <nombre> --key-out <ruta-privada>. complexity_gate.py verifica la
firma contra ese registro antes de honrar una excepción (ver _is_exempt).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import ccdd  # noqa: E402  (sign_attestation real, Ed25519)

CONTRACTS = HERE.parent / "contracts"
SLOT_ID = "complexity_exception"

def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else "complexity-agent"
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
        if ans == "y":
            rev = input("Tu ID de reviewer (registrado en reviewers.json): ").strip()
            key_path = input("Ruta a tu clave privada Ed25519 (de 'ccdd.py keygen'): ").strip()
            try:
                priv_hex = Path(key_path).read_text(encoding="utf-8").strip()
                sig = ccdd.sign_attestation(priv_hex, SLOT_ID, data["hash"])
            except (OSError, ValueError) as e:
                print(f"No se pudo firmar ({e}). Petición NO aprobada, queda pendiente.", file=sys.stderr)
                continue
            attest["complexity_exception"].append({
                "reviewer": rev,
                "content_sha256": data["hash"],
                "signature": sig
            })
            print("Aprobado y firmado (Ed25519) -> attestations.json")
        else:
            print("Rechazado.")

        p.unlink()  # Eliminar petición pendiente (aprobada+firmada, o rechazada)

    attest_path.write_text(json.dumps(attest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nProceso finalizado.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
