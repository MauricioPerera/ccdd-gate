#!/usr/bin/env python3
"""review_attestations.py — CLI para que el Arquitecto revise peticiones del agente.

Revisa los JSONs en pending_attestations/, y por cada uno muestra el código,
el motivo, y permite aprobarlo (firmándolo y metiéndolo en attestations.json)
o rechazarlo (eliminando la petición).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parent / "contracts"

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
        data = json.loads(p.read_text(encoding="utf-8"))
        print("\n" + "="*60)
        print(f"ARCHIVO: {data.get('filename')}")
        print(f"HASH:    {data.get('hash')}")
        print(f"MOTIVO:  {data.get('reason')}")
        print("-"*60)
        print(data.get("code", ""))
        print("="*60)
        
        ans = input("¿Aprobar esta excepción de complejidad? [y/N]: ").strip().lower()
        if ans == "y":
            # Extraer reviewer (usuario local) o pedirlo
            rev = input("Tu ID de reviewer (ej. mauricio): ").strip()
            # Nota: En un entorno real se pediría la clave privada Ed25519 y se usaría ccdd.sign_attestation.
            # Por simplicidad en este prototipo, guardamos la firma simbólica o el hash.
            attest["complexity_exception"].append({
                "reviewer": rev,
                "content_sha256": data["hash"],
                "signature": "simulated-signature-for-complexity"
            })
            print("Aprobado y añadido a attestations.json")
        else:
            print("Rechazado.")
        
        p.unlink()  # Eliminar petición pendiente

    attest_path.write_text(json.dumps(attest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nProceso finalizado.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
