OPCODES = {
    0x00: ("NOP", 1),
    0x3E: ("LD A, ${:02X}", 2),
    0x06: ("LD B, ${:02X}", 2),
    0xC3: ("JP ${:04X}", 3),
}

def decode_instruction(rom, pc):
    opcode = rom[pc]
    if opcode not in OPCODES:
        return f"{opcode:02X}", f"DB ${opcode:02X} (Desconocido / Datos)", 1
    fmt, size = OPCODES[opcode]
    hexb = " ".join(f"{rom[pc + i]:02X}" for i in range(size) if pc + i < len(rom))
    operands = rom[pc + 1:pc + size]
    val = int.from_bytes(operands, "little") if operands else None
    text = fmt.format(val) if val is not None else fmt
    return hexb, text, size