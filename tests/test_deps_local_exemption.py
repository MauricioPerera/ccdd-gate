"""test_deps_local_exemption.py — exención automática de módulos locales en
unauthorized_imports (runners/deps_check.py) y en la etapa gate-deps (runners/task_gate.py).

Demuestra el contrato pedido:
  (a) import de un módulo local hermano del target NO se flaggea cuando se pasa la raíz local.
  (b) import de tercero no listado SÍ se flaggea aun pasando la raíz local.
  (c) sin el parámetro `local_roots`, el comportamiento previo queda intacto (el local sí se flaggea).

Oráculo independiente, determinista, sin LLM. Usa tmp dirs reales con archivos .py / __init__.py."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
from deps_check import unauthorized_imports  # noqa: E402
import task_gate  # noqa: E402


class LocalExemptionUnit(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _write(self, name, text=""):
        p = self.d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_a_local_sibling_not_flagged_with_root(self):
        """(a) import de un módulo local hermano no se flaggea cuando se pasa la raíz local."""
        self._write("helper.py", "x = 1\n")
        src = "import helper\nimport requests\n"
        # helper resuelve a ./helper.py -> exento; requests no -> flaggeado.
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d]), ["requests"])

    def test_a_local_package_not_flagged_with_root(self):
        """(a) variante paquete: import de un paquete local (__init__.py) no se flaggea."""
        self._write("mypkg/__init__.py", "")
        src = "import mypkg\nimport requests\n"
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d]), ["requests"])

    def test_b_thirdparty_still_flagged_with_root(self):
        """(b) un tercero no listado SÍ se flaggea aunque se pase la raíz local."""
        self._write("helper.py", "x = 1\n")
        src = "import requests\n"
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d]), ["requests"])

    def test_b_nonpy_sibling_not_exempt(self):
        """(b) un nombre que NO resuelve a módulo local (no hay archivo) sigue flaggeado."""
        src = "import ghost\n"
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d]), ["ghost"])

    def test_c_no_param_keeps_previous_behavior(self):
        """(c) sin `local_roots`, el módulo local SÍ se flaggea (comportamiento previo intacto)."""
        self._write("helper.py", "x = 1\n")
        src = "import helper\nimport requests\n"
        self.assertEqual(unauthorized_imports(src, []), ["helper", "requests"])

    def test_c_empty_list_equivalent_to_none(self):
        """(c) pasar [] (en vez de omitir) tampoco exime nada: idéntico al comportamiento previo."""
        self._write("helper.py", "x = 1\n")
        src = "import helper\nimport requests\n"
        self.assertEqual(unauthorized_imports(src, [], local_roots=[]), ["helper", "requests"])

    def test_non_identifier_filename_ignored(self):
        """Un archivo `foo-bar.py` no es importable como módulo -> no exime a `foo-bar`."""
        self._write("foo-bar.py", "")
        src = "import requests\n"
        # `requests` no es local; `foo-bar` no es identifier válido y no se considera módulo.
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d]), ["requests"])

    def test_multiple_roots_union(self):
        """Múltiples roots: se exime si el módulo es local bajo cualquiera de ellos."""
        self._write("helper.py", "x = 1\n")
        other = Path(tempfile.mkdtemp())
        try:
            src = "import helper\nimport requests\n"
            self.assertEqual(unauthorized_imports(src, [], local_roots=[other, self.d]),
                             ["requests"])
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_syntax_error_returns_empty_with_roots(self):
        """Back-compat: SyntaxError sigue devolviendo [] aun con local_roots."""
        self.assertEqual(unauthorized_imports("import (", [], local_roots=[self.d]), [])

    def test_nonexistent_root_ignored(self):
        """Un root inexistente se ignora sin romper (no exime, no levanta)."""
        src = "import requests\n"
        self.assertEqual(unauthorized_imports(src, [], local_roots=[self.d / "nope"]),
                         ["requests"])


# Gate-level: la integración task_gate pasa el dir del contrato y el del target como local_roots, así
# que un target que importa un módulo hermano local PASSA con enforce_deps:true sin listar el local.
GATE_IMPL = "import helper\n\n\ndef f(x):\n    return helper.twice(x)\n"
GATE_HELPER = "def twice(x):\n    return x * 2\n"
GATE_TEST = ("import unittest\n"
             "from impl import f\n\n"
             "class T(unittest.TestCase):\n"
             "    def test_f(self):\n"
             "        self.assertEqual(f(3), 6)\n\n"
             "if __name__ == '__main__':\n"
             "    unittest.main()\n")

GATE_CONTRACT = '''---
task: deps-local-demo
intent: "Duplicar via helper local."
target: impl.py
signature: "def f(x)"
test_command: "python -m unittest test_x"
test_cwd: "."
budget: {{ cyclomatic_max: 3, nesting_max: 1, params_max: 1, lines_max: 10 }}
deps_allowed: {deps_allowed}
{enforce}tests: test_x.py
forbids: ["estado global"]
spec_version: "0.1"
---

## Intent
Duplica x usando helper local. Exito: pasa los tests, respeta el budget y la politica de deps.

## Interface
- in: x. out: x*2.

## Invariants
- f(x) == 2*x.

## Examples
- f(3) -> 6
- f(0) -> 0

## Do / Don't
- DO: usar helper. DON'T: estado global.

## Tests
test_x.py: oraculo independiente.

## Constraints
- PARAR y reportar si el budget no se cumple sin violar la interfaz.
'''


def _make_gate(deps_allowed="[]", enforce=False):
    d = Path(tempfile.mkdtemp())
    (d / "impl.py").write_text(GATE_IMPL, encoding="utf-8")
    (d / "helper.py").write_text(GATE_HELPER, encoding="utf-8")
    (d / "test_x.py").write_text(GATE_TEST, encoding="utf-8")
    enforce_line = "enforce_deps: true\n" if enforce else ""
    (d / "task.md").write_text(
        GATE_CONTRACT.format(deps_allowed=deps_allowed, enforce=enforce_line), encoding="utf-8")
    return d / "task.md"


class LocalExemptionGate(unittest.TestCase):
    def test_enforce_passes_local_sibling_exempt(self):
        """gate-deps: con enforce_deps:true y deps_allowed=[], un import de módulo hermano local
        del target NO se flaggea (exención automática) -> PASS."""
        t = _make_gate(deps_allowed="[]", enforce=True)
        try:
            v = task_gate.gate(str(t))
            self.assertEqual(v["verdict"], "PASS", v)
        finally:
            shutil.rmtree(t.parent, ignore_errors=True)

    def test_enforce_still_flags_thirdparty_with_local_present(self):
        """gate-deps: aun habiendo un helper local que se exime, un tercero (yaml) no listado SÍ se
        flaggea. El impl usa helper (local, exento) para que los tests pasen y el gate llegue a
        gate-deps en vez de fallar en gate1-tests."""
        d = Path(tempfile.mkdtemp())
        try:
            (d / "impl.py").write_text(
                "import yaml\nimport helper\n\n\ndef f(x):\n    return helper.twice(x)\n",
                encoding="utf-8")
            (d / "helper.py").write_text(GATE_HELPER, encoding="utf-8")
            (d / "test_x.py").write_text(GATE_TEST, encoding="utf-8")
            (d / "task.md").write_text(
                GATE_CONTRACT.format(deps_allowed="[]", enforce="enforce_deps: true\n"),
                encoding="utf-8")
            v = task_gate.gate(str(d / "task.md"))
            self.assertEqual(v["verdict"], "FAIL", v)
            self.assertEqual(v["stage"], "gate-deps")
            self.assertIn("yaml", v.get("unauthorized", []))
            self.assertNotIn("helper", v.get("unauthorized", []))
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()