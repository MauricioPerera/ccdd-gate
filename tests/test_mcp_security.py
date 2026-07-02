"""test_mcp_security.py — regresiones de los 4 hallazgos de la auditoría de seguridad sobre
complexity_mcp.py (servidor MCP stdio JSON-RPC). Determinista, sin LLM.

Cubre:
  (a) request_human_attestation con agent="../../x" -> error y NO crea archivo fuera de contracts/.
  (b) _prepare_ephemeral_task rechaza un target absoluto / con `..` (path traversal del escritor).
  (c) un request JSON-RPC malformado (sin name, no-dict, JSON roto) -> error JSON-RPC bien formado
      y el server sigue vivo (no excepción no capturada).
  (d) judge_audit ignora un api_url inyectado por el cliente (SSRF/exfiltración)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import complexity_mcp  # noqa: E402


class AttestationPathTraversalTest(unittest.TestCase):
    def test_agent_traversal_rejected_and_no_file_outside_contracts(self):
        # Antes: agent="../../x" construía CONTRACTS/../../x/pending_attestations y escribía un
        # .json fuera de contracts/. Ahora: error claro y nada se escribe.
        before = {p for p in (REPO / "x").rglob("*")} if (REPO / "x").exists() else set()
        res = complexity_mcp.request_human_attestation(
            {"code": "def f():\n    return 1\n", "reason": "test", "agent": "../../x"})
        self.assertIn("error", res)
        self.assertNotIn("status", res)
        # No se creó archivo fuera de contracts/ (el path traversal no materializó nada).
        after = {p for p in (REPO / "x").rglob("*")} if (REPO / "x").exists() else set()
        self.assertEqual(before, after)

    def test_agent_invalid_rejected(self):
        res = complexity_mcp.request_human_attestation(
            {"code": "def f():\n    return 1\n", "reason": "test", "agent": "evil-agent"})
        self.assertIn("error", res)

    def test_agent_valid_still_works(self):
        # Un agent válido escribe dentro de contracts/<agent>/pending_attestations/ (regresión: el
        # fix no rompe el camino feliz). Limpia el archivo creado.
        res = complexity_mcp.request_human_attestation(
            {"code": "def g():\n    return 2\n", "reason": "test legit",
             "agent": "complexity-agent"})
        self.assertEqual(res.get("status"), "Atestación solicitada")
        h = res["hash"]
        out = REPO / "contracts" / "complexity-agent" / "pending_attestations" / f"{h}.json"
        self.assertTrue(out.exists())
        out.unlink(missing_ok=True)


_CONTRACT_TMPL = """---
task: {task}
intent: hace algo simple
target: {target}
signature: "def f() -> int"
budget: {{ cyclomatic_max: 3, nesting_max: 1, params_max: 2, lines_max: 10 }}
deps_allowed: []
forbids: ["usar eval"]
tests: tests/test_f.py
test_command: "python -m pytest tests/test_f.py"
spec_version: "0.1"
require_test_approval: false
---

## Intent
Devolver un entero.

## Interface
- Salida: int.

## Invariants
- f() es un entero.

## Examples
- f() -> 1

## Do / Don't
- DO: devolver int.

## Tests
- Oraculo independiente.

## Constraints
- Sin deps. PARAR y reportar si el budget no se cumple.
"""


class EphemeralTargetTraversalTest(unittest.TestCase):
    def _write_contract(self, tmp, target):
        task = tmp / "task.md"
        task.write_text(_CONTRACT_TMPL.format(task="t", target=target), encoding="utf-8")
        return task

    def test_absolute_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            task = self._write_contract(tmp, str(tmp / "evil.py"))
            _ctx, err = complexity_mcp._prepare_ephemeral_task({"task_path": str(task)})
            self.assertIsNone(_ctx)
            self.assertIsNotNone(err)
            self.assertEqual(err["status"], "FAIL")
            self.assertIn("escapa", err["reason"])

    def test_dotdot_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            # crea el archivo fuera para que .exists() sería True si no se validara contención
            outside = tmp.parent / "evil_outside.py"
            outside.write_text("def f():\n    return 1\n", encoding="utf-8")
            try:
                task = self._write_contract(tmp, "../evil_outside.py")
                _ctx, err = complexity_mcp._prepare_ephemeral_task({"task_path": str(task)})
                self.assertIsNone(_ctx)
                self.assertEqual(err["status"], "FAIL")
                self.assertIn("escapa", err["reason"])
            finally:
                outside.unlink(missing_ok=True)

    def test_legit_target_still_loads(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "f.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            task = self._write_contract(tmp, "f.py")
            ctx, err = complexity_mcp._prepare_ephemeral_task({"task_path": str(task)})
            self.assertIsNone(err)
            self.assertIsNotNone(ctx)
            self.assertTrue(ctx["target"].exists())


class JsonRpcRobustnessTest(unittest.TestCase):
    def _run_main(self, lines):
        """Corre main() alimentando `lines` por stdin y captura stdout. Devuelve lista de msgs."""
        inp = io.StringIO("\n".join(lines) + "\n")
        out = io.StringIO()
        orig_stdin, sys.stdin = sys.stdin, inp
        try:
            with contextlib.redirect_stdout(out):
                complexity_mcp.main()
        finally:
            sys.stdin = orig_stdin
        return [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]

    def test_broken_json_returns_parse_error_and_survives(self):
        # JSON roto -> -32700 y el loop sigue vivo para el siguiente request válido.
        msgs = self._run_main(["{not valid json", json.dumps(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list"})])
        self.assertEqual(msgs[0]["error"]["code"], -32700)
        self.assertEqual(msgs[1]["result"]["tools"], complexity_mcp.TOOLS)

    def test_non_dict_request_returns_invalid_request(self):
        msgs = self._run_main(["[1, 2, 3]", '"hello"'])
        self.assertEqual(msgs[0]["error"]["code"], -32600)
        self.assertEqual(msgs[1]["error"]["code"], -32600)

    def test_tools_call_without_name_returns_error(self):
        # Antes: params["name"] tiraba KeyError y mataba el server. Ahora: error JSON-RPC.
        msgs = self._run_main([json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                           "params": {"arguments": {}}})])
        # tools/call sin name -> el handler responde con error (isError o jsonrpc error).
        body = msgs[0]
        # Puede ser error JSON-RPC (-32602) o contenido isError; ambos son respuestas válidas.
        self.assertTrue(body.get("error") or body.get("result", {}).get("isError"))

    def test_notification_no_id_no_response(self):
        # notificación (sin id) no produce respuesta; no debe tirar excepción.
        msgs = self._run_main([json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})])
        self.assertEqual(msgs, [])

    def test_unsupported_method_returns_32601(self):
        msgs = self._run_main([json.dumps({"jsonrpc": "2.0", "id": 11, "method": "foo/bar"})])
        self.assertEqual(msgs[0]["error"]["code"], -32601)


class JudgeAuditSsrfTest(unittest.TestCase):
    def test_injected_api_url_ignored(self):
        # El schema solo declara eval_path; el handler NO debe leer api_url/provider de args.
        # Verificamos que un api_url inyectado NO llega a judge_audit.audit: spy sobre la llamada.
        import judge_audit as _ja
        captured = {}

        def _spy(path, provider="stub", api_url=""):
            captured["provider"] = provider
            captured["api_url"] = api_url
            return {"ok": True, "golden_cases": 0, "agreement": 0.0}

        orig = _ja.audit
        _ja.audit = _spy
        # Garantiza que el operador no habilitó api_url por entorno (test aislado).
        with contextlib.ExitStack() as stack:
            for k in ("CCDD_JUDGE_PROVIDER", "CCDD_JUDGE_API"):
                stack.enter_context(_unset_env(k))
            # Un eval_path válido (existe en disco) para pasar el guard de path.
            eval_path = self._make_minimal_eval()
            try:
                complexity_mcp.judge_audit(
                    {"eval_path": str(eval_path),
                     "api_url": "http://evil.example.com/exfil", "provider": "openai"})
            finally:
                _ja.audit = orig
        self.assertEqual(captured["api_url"], "")
        self.assertEqual(captured["provider"], "stub")

    def _make_minimal_eval(self):
        # eval-contract mínimo que pasa el guard de path (existe en disco); el spy reemplaza audit.
        d = Path(tempfile.mkdtemp())
        p = d / "eval.md"
        p.write_text("---\ndataset: cases.jsonl\ntarget: agent.py\nagent_entry: run\n---\n# eval\n",
                     encoding="utf-8")
        return p


@contextlib.contextmanager
def _unset_env(key):
    had = key in os.environ
    old = os.environ.get(key)
    if had:
        del os.environ[key]
    try:
        yield
    finally:
        if had:
            os.environ[key] = old


if __name__ == "__main__":
    unittest.main()