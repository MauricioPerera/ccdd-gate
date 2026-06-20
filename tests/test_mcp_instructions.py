"""test_mcp_instructions.py — el servidor MCP debe entregar instrucciones de uso en `initialize`
(campo MCP `instructions`) y la plantilla embebida debe lintar verde. Determinista, sin LLM.

Motivación: en uso real el modelo grande perdía mucho tiempo infiriendo el formato del contrato
por error-y-reintento (incluso leyendo copias obsoletas del fuente). Las instrucciones se lo dan
explícito al conectar."""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import complexity_mcp  # noqa: E402

EXAMPLE_TEST_CODE = "def test_add():\n    assert add(2, 3) == 5\n    assert add(0, 0) == 0\n"


class McpInstructionsTest(unittest.TestCase):
    def test_instructions_present_and_substantive(self):
        ins = complexity_mcp.INSTRUCTIONS
        self.assertIsInstance(ins, str)
        self.assertGreater(len(ins), 400)
        for tok in ("lint_task_contract", "run_ephemeral_agent", "test_cwd",
                    "## Intent", "signature", "tc-no-algorithm",
                    "nemotron-3-nano:30b-cloud", "11434"):
            self.assertIn(tok, ins, msg=f"falta '{tok}' en las instrucciones")

    def test_initialize_returns_instructions(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            complexity_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        out = json.loads(buf.getvalue().strip())
        self.assertEqual(out["result"]["instructions"], complexity_mcp.INSTRUCTIONS)

    def test_embedded_example_lints_green(self):
        # el contrato de ejemplo que se envía en las instrucciones DEBE lintar limpio: si no, la
        # plantilla que ve el agente estaría rota.
        res = complexity_mcp.lint_task_contract(
            {"contract_text": complexity_mcp._MINIMAL_CONTRACT, "test_code": EXAMPLE_TEST_CODE})
        self.assertTrue(res["ok"], msg=str(res["findings"]))


if __name__ == "__main__":
    unittest.main()
