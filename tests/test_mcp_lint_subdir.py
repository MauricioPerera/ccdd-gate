"""test_mcp_lint_subdir.py — regresión del bug: lint_task_contract (MCP) reventaba con
FileNotFoundError cuando `tests:` traía un subdirectorio, porque escribía el test_code sin
crear los dirs intermedios. Ahora debe lintar sin excepción. Determinista, sin LLM."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import complexity_mcp  # noqa: E402

CONTRACT = """---
task: add-two
intent: sumar dos enteros
target: add.py
signature: "def add(a: int, b: int) -> int"
budget:
  cyclomatic_max: 3
  nesting_max: 1
  params_max: 2
  lines_max: 10
deps_allowed: []
forbids:
  - "convertir a str"
tests: tests/sub/test_add.py
test_command: "python -m pytest"
spec_version: "0.1"
require_test_approval: true
---

## Intent
Sumar dos enteros.

## Interface
- Entrada: a, b enteros. Salida: su suma.

## Invariants
- add(a, b) devuelve a + b.

## Examples
- add(2, 3) da 5.
- add(0, 0) da 0.

## Do / Don't
- DO: devolver int.
- DON'T: convertir a str.

## Tests
- Oraculo independiente con casos fijos.

## Constraints
- Sin deps. PARAR y reportar si el budget no se cumple sin violar la interfaz.
"""

TEST_CODE = "def test_add():\n    assert add(2, 3) == 5\n"


class McpLintSubdirTest(unittest.TestCase):
    def test_subdir_tests_no_excepta_y_lintea_verde(self):
        # Antes: FileNotFoundError por el subdir `tests/sub/`. Ahora: lint normal.
        res = complexity_mcp.lint_task_contract({"contract_text": CONTRACT, "test_code": TEST_CODE})
        self.assertTrue(res["tests_provided"])
        self.assertEqual(res["errors"], 0, msg=str(res["findings"]))
        self.assertTrue(res["ok"])

    def test_sin_test_code_reporta_finding_no_excepcion(self):
        # Sin test_code, la regla tc-tests-frozen debe ser un finding, no un crash.
        res = complexity_mcp.lint_task_contract({"contract_text": CONTRACT})
        self.assertFalse(res["tests_provided"])
        self.assertTrue(any(f["rule"] == "tc-tests-frozen" for f in res["findings"]))


if __name__ == "__main__":
    unittest.main()
