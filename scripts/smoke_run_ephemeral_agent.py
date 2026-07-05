import sys
from pathlib import Path

sys.path.insert(0, str(Path("d:/repos/ccddgate/ccdd-gate/runners").resolve()))
import complexity_mcp

args = {
    "task_path": "d:/repos/ccddgate/ccdd-gate/examples/sandbox/task.md",
    "model": "gemma-4-12b-coder",
    "api_url": "http://localhost:1234/v1"
}

import urllib.request
import json

mocked_code = """```python
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
```"""

class MockResponse:
    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": mocked_code}}]
        }).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass

def mock_urlopen(req, timeout=None):
    return MockResponse()

urllib.request.urlopen = mock_urlopen

print("Invocando run_ephemeral_agent vía MCP interno (con LM Studio mockeado)...")
result = complexity_mcp.run_ephemeral_agent(args)

print(json.dumps(result, indent=2, ensure_ascii=False))
