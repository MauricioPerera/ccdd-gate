"""test_mcp_instructions.py — el servidor MCP debe entregar instrucciones de uso en `initialize`
(campo MCP `instructions`) y la plantilla embebida debe lintar verde. Determinista, sin LLM.

Motivación: en uso real el modelo grande perdía mucho tiempo infiriendo el formato del contrato
por error-y-reintento (incluso leyendo copias obsoletas del fuente). Las instrucciones se lo dan
explícito al conectar."""
import contextlib
import io
import json
import os
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
                    "kind: group", "children", "conforms_to", "run_integration_gate",
                    "NO escribas"):
            self.assertIn(tok, ins, msg=f"falta '{tok}' en las instrucciones")

    def test_initialize_returns_instructions(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            complexity_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        out = json.loads(buf.getvalue().strip())
        self.assertEqual(out["result"]["instructions"], complexity_mcp.INSTRUCTIONS)

    def test_executor_default_and_env_configurable(self):
        # El SERVIDOR/operador decide el implementador por defecto (no el LLM): si el llamador no pasa
        # model/api_url, run_ephemeral_agent usa estos. El operador puede sobreescribir por entorno
        # (CCDD_EXECUTOR_MODEL / CCDD_EXECUTOR_API); el LLM no. Default validado por benchmark.
        self.assertEqual(complexity_mcp.DEFAULT_EXECUTOR_MODEL,
                         os.environ.get("CCDD_EXECUTOR_MODEL", "qwen3-coder:480b-cloud"))
        self.assertIn("11434", complexity_mcp.DEFAULT_EXECUTOR_API)

    def test_run_task_gate_removed_from_surface(self):
        # El hatch de implementacion directa (run_task_gate(code)) se saca de la superficie MCP:
        # implementar -> run_ephemeral_agent; verificar en disco -> run_integration_gate.
        self.assertNotIn("run_task_gate", complexity_mcp.DISPATCH)
        self.assertFalse(any(t["name"] == "run_task_gate" for t in complexity_mcp.TOOLS))
        self.assertIn("run_integration_gate", complexity_mcp.DISPATCH)

    def test_ephemeral_schema_does_not_expose_model(self):
        # El LLM NO debe poder elegir el modelo: el tool solo acepta task_path. model/api_url
        # los fija el servidor. Congela el diseño "el MCP decide, no el LLM".
        tool = next(t for t in complexity_mcp.TOOLS if t["name"] == "run_ephemeral_agent")
        props = tool["inputSchema"]["properties"]
        self.assertEqual(set(props), {"task_path"})
        self.assertNotIn("model", props)
        self.assertNotIn("api_url", props)

    def test_embedded_example_lints_green(self):
        # el contrato de ejemplo que se envía en las instrucciones DEBE lintar limpio: si no, la
        # plantilla que ve el agente estaría rota.
        res = complexity_mcp.lint_task_contract(
            {"contract_text": complexity_mcp._MINIMAL_CONTRACT, "test_code": EXAMPLE_TEST_CODE})
        self.assertTrue(res["ok"], msg=str(res["findings"]))


if __name__ == "__main__":
    unittest.main()
