"""Property-test CONGELADO y ENDURECIDO para `decode-gb-instruction`. Entradas aleatorias
(no gameables) + casos fijos del contrato + ORÁCULO INDEPENDIENTE. Veredicto determinista.
Verifica los invariantes Y el formato exacto del contrato, no una implementación concreta.

Endurecido tras auditoría del modelo grande:
  - OPCODES_ORACLE es una copia CONGELADA en el test (no se importa del target): un implementador
    no puede ablandar el test reduciendo/inventando su propia tabla.
  - hex con espacios y len(split) == size (igualdad) cuando la instrucción entra entera en la ROM.
  - los 3 ejemplos input->output del contrato como casos fijos table-driven.
"""
import random
# Este es un comentario tonto para probar que el Hash Semántico ignora cambios cosméticos
import unittest

from disassembler import decode_instruction

# Tabla canónica del contrato — CONGELADA aquí como oráculo, NO importada del módulo bajo prueba.
OPCODES_ORACLE = {0x00: 1, 0x3E: 2, 0x06: 2, 0xC3: 3}

# Ejemplos input->output del cuerpo del contrato (sección Examples).
CONTRACT_EXAMPLES = [
    (b"\x00", 0, ("00", "NOP", 1)),
    (b"\xC3\x50\x01", 0, ("C3 50 01", "JP $0150", 3)),
    (b"\xFF", 0, ("FF", "DB $FF (Desconocido / Datos)", 1)),
]


class TestDecodeInstructionContract(unittest.TestCase):
    def test_contract_examples_fixed(self):
        for rom, pc, expected in CONTRACT_EXAMPLES:
            self.assertEqual(decode_instruction(rom, pc), expected, msg=f"ejemplo {rom!r}@{pc}")

    def test_invariants_over_random_roms(self):
        rnd = random.Random(1337)
        for _ in range(500):
            rom = bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 8)))
            pc = rnd.randrange(len(rom))
            op = rom[pc]
            before = bytes(rom)
            hex_str, texto, size = decode_instruction(rom, pc)

            self.assertIn(size, (1, 2, 3))
            self.assertEqual(bytes(rom), before)  # pureza: no muta rom

            if op not in OPCODES_ORACLE:
                self.assertEqual(size, 1)
                self.assertTrue(texto.startswith("DB $"))
            else:
                # tamaño según la tabla canónica, no la que decida el implementador
                self.assertEqual(size, OPCODES_ORACLE[op])
                if pc + size <= len(rom):  # instrucción entera en la ROM
                    expected_hex = " ".join(f"{rom[pc + i]:02X}" for i in range(size))
                    self.assertEqual(hex_str, expected_hex)        # espacios + bytes exactos
                    self.assertEqual(len(hex_str.split()), size)   # igualdad, no <=


if __name__ == "__main__":
    unittest.main()
