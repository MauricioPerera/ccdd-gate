---
task: decode-gb-instruction
intent: "Decodificar una instrucción SM83 en una posición de la ROM."
target: disassembler.py
signature: "def decode_instruction(rom: bytes, pc: int) -> tuple[str, str, int]"
test_command: "python -m unittest test_decode_instruction.py"
budget: { cyclomatic_max: 8, nesting_max: 2, params_max: 2, lines_max: 20 }
deps_allowed: []
forbids: ["bucle while", "estado global", "print"]
depends_on: ["OPCODES: dict[int, tuple[str, int]] (ya definido en el módulo)"]
tests: test_decode_instruction.py
spec_version: "0.1"
sign: true
tests_sha256: "c339d9cff0ae59b4fdf37c6f36a538e1942e573b9c4040e3ac9fbfd4b855d9ce"
---

## Intent
Dada la ROM y un puntero `pc`, devolver `(hex_str, texto, size)` de la instrucción en `pc`.
Éxito: pasa los property-tests congelados y respeta el budget.

## Interface
```
in:  rom: bytes (len >= 1), pc: int (0 <= pc < len(rom))
out: (hex_str: str, texto: str, size: int)
     - opcode conocido (en OPCODES): size = OPCODES[op][1]; texto = formato con operandos
     - opcode desconocido:           size = 1; texto = "DB $XX (Desconocido / Datos)"
error: no lanza; pc fuera de rango es responsabilidad del caller
```

## OPCODES (tabla canónica COMPLETA — implementar exactamente estos 4, sin omitir ninguno)
```
0x00 -> ("NOP", 1)              # sin operandos
0x06 -> ("LD B, ${:02X}", 2)    # 1 byte operando, %02X
0x3E -> ("LD A, ${:02X}", 2)    # 1 byte operando, %02X
0xC3 -> ("JP ${:04X}", 3)       # 2 bytes operando little-endian, %04X
```
Operandos little-endian: `val = int.from_bytes(rom[pc+1:pc+size], "little")`; `texto = fmt.format(val)`
(para size 1 el texto es el literal `fmt`). `hex_str` = bytes `[pc, pc+size)` en MAYÚSCULAS separados por
espacio (`"C3 50 01"`), omitiendo solo los que caen fuera de la ROM.

## Invariants
- `size` pertenece a {1, 2, 3} siempre.
- `len(hex_str.split())` <= size (menos solo al toparse el fin de la ROM).
- opcode no presente en OPCODES => `size == 1` y `texto` empieza con `"DB $"`.
- Función pura: no muta `rom`.

## Examples
- `decode_instruction(b"\x00", 0)` → `("00", "NOP", 1)` (con NOP en OPCODES)
- `decode_instruction(b"\xC3\x50\x01", 0)` → `("C3 50 01", "JP $0150", 3)`
- `decode_instruction(b"\xFF", 0)` → `("FF", "DB $FF (Desconocido / Datos)", 1)`

## Do / Don't
- DO: tabla `OPCODES` para el despacho; operandos little-endian.
- DON'T: no abrir archivos, no `while`, no estado global.
- Patrón a imitar: el manejo de `OPCODES` del módulo.

## Tests
Property-test congelado (`test_decode_instruction.py`): ROMs aleatorias + `pc` válido; asserta los
4 invariantes en cada caso. No depende de la implementación; existe antes de implementar.

## Constraints
- NO modificar `OPCODES` ni nada fuera de `decode_instruction`.
- NO añadir dependencias; `deps_allowed` está vacío.
- NO `print` ni I/O.
- PARAR y reportar si el budget no se puede cumplir sin violar la interfaz. Sin workarounds silenciosos.
