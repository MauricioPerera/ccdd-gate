OPCODES = {
    0x00: ("NOP", 1),
    0x06: ("LD B, ${:02X}", 2),
    0x3e: ("LD A, ${:02X}", 2),
    0xc3: ("JP ${:04X}", 3),
}


def decode_instruction(rom, pc):
    opcode = rom[pc]
    if opcode not in OPCODES:
        return (f"{opcode:02X}", f"DB ${opcode:02X} (Desconocido / Datos)", 1)

    fmt, size = OPCODES[opcode]
    bytes_to_parse = rom[pc + 1 : pc + size]
    operand = int.from_bytes(bytes_to_parse, "little")
    hex_str = " ".join(f"{b:02X}" for b in rom[pc : pc + size])

    return (hex_str, fmt.format(operand), size)
