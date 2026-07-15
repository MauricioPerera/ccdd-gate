"""test_gates.py — tests CONGELADOS del núcleo determinista (tc_lint + task_gate). Sin LLM.
El gate que juzga a los demás se autojuzga: veredictos reproducibles corrida a corrida.

PASS usa el sandbox estable (examples/sandbox/*). Los casos FAIL/INVALID construyen su propia
variante en un tempdir (budget apretado, impl rota, aprobación faltante) — sin tocar fixtures.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import tc_lint    # noqa: E402
import task_gate  # noqa: E402

SANDBOX = REPO / "examples" / "sandbox"
TASK = SANDBOX / "task.md"
TEST = SANDBOX / "test_decode_instruction.py"
GOOD_IMPL = SANDBOX / "disassembler.py"

BROKEN_CONTRACT = """---
task: malo
intent: hace una cosa y además otra
budget: { cyclomatic_max: 999 }
---
# cuerpo sin secciones
"""


def _variant(budget_repl=None, impl_text=None):
    """Copia el sandbox a un tempdir y opcionalmente aprieta el budget o rompe la impl.
    Devuelve la ruta del task.md en el tempdir (el caller borra el dir)."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(TEST, d / "test_decode_instruction.py")
    (d / "disassembler.py").write_text(
        impl_text if impl_text is not None else GOOD_IMPL.read_text(encoding="utf-8"), encoding="utf-8")
    task = TASK.read_text(encoding="utf-8")
    if budget_repl:
        task = task.replace(*budget_repl)
    (d / "task.md").write_text(task, encoding="utf-8")
    return d / "task.md"


BAD_IMPL = '''OPCODES = {0x00: ("NOP", 1), 0x06: ("LD B, ${:02X}", 2),
           0x3E: ("LD A, ${:02X}", 2), 0xC3: ("JP ${:04X}", 3)}


def decode_instruction(rom, pc):
    opcode = rom[pc]
    if opcode not in OPCODES:
        return f"{opcode:02X}", f"DB ${opcode:02X} (Desconocido / Datos)", 2  # rompe invariante
    fmt, size = OPCODES[opcode]
    hexb = " ".join(f"{rom[pc + i]:02X}" for i in range(size) if pc + i < len(rom))
    operands = rom[pc + 1:pc + size]
    val = int.from_bytes(operands, "little") if operands else None
    return hexb, (fmt.format(val) if val is not None else fmt), size
'''


class TestTcLint(unittest.TestCase):
    def test_valid_contract_no_errors(self):
        findings = tc_lint.lint(TASK)
        self.assertEqual([f for f in findings if f["level"] == "error"], [])

    def test_broken_contract_flags_rules(self):
        d = Path(tempfile.mkdtemp())
        try:
            p = d / "task.md"
            p.write_text(BROKEN_CONTRACT, encoding="utf-8")
            rules = {f["rule"] for f in tc_lint.lint(p) if f["level"] == "error"}
        finally:
            shutil.rmtree(d, ignore_errors=True)
        for expected in ("tc-required", "tc-intent-atomic", "tc-budget-sane", "tc-sections", "tc-stop-rule"):
            self.assertIn(expected, rules)


class TestTaskGate(unittest.TestCase):
    def test_pass_on_sandbox(self):
        v = task_gate.gate(str(TASK))
        self.assertEqual(v["verdict"], "PASS")

    def test_fail_gate1_over_budget(self):
        p = _variant(budget_repl=("cyclomatic_max: 8", "cyclomatic_max: 1"))
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "gate2-complexity")

    def test_fail_gate2_broken_impl(self):
        p = _variant(impl_text=BAD_IMPL)
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "gate1-tests")

    def test_invalid_unapproved_tests(self):
        p = _variant(budget_repl=("spec_version:", "require_test_approval: true\nspec_version:"))
        try:
            v = task_gate.gate(str(p))
        finally:
            shutil.rmtree(p.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "INVALID")
        self.assertEqual(v["stage"], "test-approval")


class TestTestCwd(unittest.TestCase):
    """Regresión del fix de CWD: por defecto los tests corren en target.parent (compat), pero
    `test_cwd` permite correrlos desde el directorio del contrato (raíz del proyecto)."""

    def test_default_cwd_is_target_parent(self):
        target = Path(tempfile.gettempdir()) / "proj" / "pkg" / "impl.py"
        self.assertEqual(task_gate._resolve_test_cwd({}, target, target.parents[1]), str(target.parent))

    def test_test_cwd_resolves_relative_to_contract(self):
        d = Path(tempfile.mkdtemp())
        try:
            got = task_gate._resolve_test_cwd({"test_cwd": "."}, d / "pkg" / "impl.py", d)
            self.assertEqual(got, str(d.resolve()))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_gate_run_tests_honors_cwd(self):
        # test en el dir del contrato, target en un subdir. Sin test_cwd el CWD es el subdir del
        # target y el comando no encuentra el test (FAIL); con test_cwd='.' sí (PASS).
        d = Path(tempfile.mkdtemp())
        try:
            (d / "pkg").mkdir()
            (d / "pkg" / "impl.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
            (d / "t_f.py").write_text("print('ok')\n", encoding="utf-8")
            target, tests = d / "pkg" / "impl.py", d / "t_f.py"
            fm = {"test_command": "python t_f.py", "tests": "t_f.py"}
            without = task_gate._gate_run_tests(fm, target, tests, d)
            self.assertIsNotNone(without)
            self.assertEqual(without["stage"], "gate1-tests")
            withcwd = task_gate._gate_run_tests({**fm, "test_cwd": "."}, target, tests, d)
            self.assertIsNone(withcwd)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_test_command_single_quotes_survive(self):
        # shlex (no shell): un argumento entre comillas simples sobrevive — en cmd.exe (shell=True)
        # se rompía en los espacios. Aquí el script imprime el nº de args; debe ser exactamente 1.
        d = Path(tempfile.mkdtemp())
        try:
            (d / "impl.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
            (d / "t.py").write_text("import sys\nassert len(sys.argv) == 2, sys.argv\n", encoding="utf-8")
            fm = {"test_command": "python t.py 'un arg con espacios'", "tests": "t.py", "test_cwd": "."}
            res = task_gate._gate_run_tests(fm, d / "impl.py", d / "t.py", d)
            self.assertIsNone(res)
        finally:
            shutil.rmtree(d, ignore_errors=True)


def _group_fixture(impl_text=None, integration_ok=True, with_children=True, spec=None):
    """Grupo en tempdir: 1 hija (copia del sandbox conocido-bueno) + test de integración.
    spec: None | 'ok' | 'missing' | 'malformed' -> añade un `produces: [api.yaml]` y, salvo
    'missing', escribe api.yaml (bien o mal formado) para ejercer el gate de spec compartida."""
    d = Path(tempfile.mkdtemp())
    shutil.copy(TEST, d / "test_decode_instruction.py")
    (d / "disassembler.py").write_text(
        impl_text if impl_text is not None else GOOD_IMPL.read_text(encoding="utf-8"), encoding="utf-8")
    (d / "child.md").write_text(TASK.read_text(encoding="utf-8"), encoding="utf-8")
    # script stdlib (no pytest: CI es zero-dep). assert a nivel módulo: True->exit0, False->exit1.
    (d / "test_integration.py").write_text(f"assert {integration_ok}\n", encoding="utf-8")
    if spec == "ok":
        (d / "api.yaml").write_text("openapi: 3.0.0\npaths: {}\n", encoding="utf-8")
    elif spec == "malformed":
        (d / "api.yaml").write_text("[1, 2", encoding="utf-8")  # YAML flow sin cerrar
    children = "children:\n  - child.md\n" if with_children else ""
    spec_block = "produces:\n  - api.yaml\n" if spec is not None else ""
    (d / "group.md").write_text(
        "---\nkind: group\ntask: compose-x\nintent: Componer las piezas.\n" + children + spec_block +
        "integration_tests: test_integration.py\n"
        'integration_test_command: "python test_integration.py"\n'
        'test_cwd: "."\nspec_version: "0.1"\n---\n\n## Intent\nComponer.\n', encoding="utf-8")
    return d / "group.md"


class TestIntegrationGate(unittest.TestCase):
    def test_pass_when_children_and_integration_pass(self):
        g = _group_fixture()
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "PASS")
        self.assertEqual(v["stage"], "integration-all")

    def test_fail_when_a_child_fails(self):
        g = _group_fixture(impl_text=BAD_IMPL)
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "integration-children")
        self.assertEqual(v["failed_child"], "child.md")

    def test_fail_when_integration_tests_fail(self):
        # las hijas pasan, pero la composición no: debe fallar en integration-tests, no antes.
        g = _group_fixture(integration_ok=False)
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "integration-tests")

    def test_invalid_when_no_children(self):
        g = _group_fixture(with_children=False)
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "INVALID")
        # gate() ahora lintea el grupo primero (GROUP_RULES): un grupo sin children falla en
        # 'contract' (lint), no en 'integration-contract'. Cualquiera de los dos es válido.
        self.assertIn(v["stage"], ("contract", "integration-contract"))

    def test_pass_with_wellformed_shared_spec(self):
        g = _group_fixture(spec="ok")
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "PASS")

    def test_fail_when_shared_spec_missing(self):
        g = _group_fixture(spec="missing")
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "integration-spec")

    def test_fail_when_shared_spec_malformed(self):
        g = _group_fixture(spec="malformed")
        try:
            v = task_gate.gate(str(g))
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "FAIL")
        self.assertEqual(v["stage"], "integration-spec")


class TestGateAnnotations(unittest.TestCase):
    """gate3-annotations: nombres en anotaciones sin importar/definir (el bug que el runtime 3.14
    enmascara). Determinista, zero-dep, solo Python."""

    def _target(self, src):
        d = Path(tempfile.mkdtemp())
        (d / "t.py").write_text(src, encoding="utf-8")
        return d, d / "t.py"

    def test_flags_undefined_annotation_name(self):
        d, p = self._target("def f(x: Node):\n    return x\n")
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNotNone(r)
        self.assertEqual(r["stage"], "gate3-annotations")
        self.assertIn("Node", r["detail"])

    def test_imported_name_ok(self):
        d, p = self._target("from m import Node\n\n\ndef f(x: Node):\n    return x\n")
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)

    def test_builtins_ok(self):
        d, p = self._target("def f(x: dict, y: int) -> tuple:\n    return (y,)\n")
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)

    def test_non_python_skipped(self):
        d, p = self._target("function f(x: Node) {}")
        try:
            r = task_gate._gate_annotations({"language": "javascript"}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)

    def test_star_import_not_flagged(self):
        d, p = self._target("from m import *\n\n\ndef f(x: Node):\n    return x\n")
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)

    def test_tuple_unpacking_defines_names(self):
        # A, B = ... define A y B: usarlos en anotación NO debe marcar falso positivo.
        d, p = self._target("A, B = object(), object()\n\n\ndef f(x: A) -> B:\n    return x\n")
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)

    @unittest.skipIf(sys.version_info < (3, 12), "PEP 695 requiere Python 3.12+")
    def test_pep695_type_alias_and_generics(self):
        src = "type Point = tuple\n\n\ndef f[T](x: T) -> Point:\n    return x\n"
        d, p = self._target(src)
        try:
            r = task_gate._gate_annotations({}, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)
        self.assertIsNone(r)


class TestRunIntegrationGate(unittest.TestCase):
    """La tool MCP run_integration_gate gatea un grupo sobre disco REAL (sin sandbox), que es lo
    que la composición necesita (el test de integración importa los módulos hijos ensamblados)."""

    def _mcp(self):
        sys.path.insert(0, str(REPO / "runners"))
        import complexity_mcp
        return complexity_mcp

    def test_runs_group_on_real_disk(self):
        g = _group_fixture()
        try:
            v = self._mcp().run_integration_gate({"task_path": str(g)})
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(v["verdict"], "PASS")
        self.assertEqual(v["stage"], "integration-all")

    def test_missing_path_is_invalid(self):
        v = self._mcp().run_integration_gate({"task_path": str(REPO / "no" / "existe.md")})
        self.assertEqual(v["verdict"], "INVALID")


class TestGroupLint(unittest.TestCase):
    def test_good_group_lints_clean(self):
        g = _group_fixture()
        try:
            errs = [f for f in tc_lint.lint(g) if f["level"] == "error"]
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertEqual(errs, [], msg=str(errs))

    def test_group_missing_children_flagged(self):
        g = _group_fixture(with_children=False)
        try:
            rules = {f["rule"] for f in tc_lint.lint(g) if f["level"] == "error"}
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertIn("tc-group-required", rules)

    def test_group_does_not_get_function_rules(self):
        # un grupo no debe exigir signature/target/secciones (reglas de función), ni que el
        # schema (rama group) dispare tc-schema por faltar campos de función.
        g = _group_fixture()
        try:
            rules = {f["rule"] for f in tc_lint.lint(g)}
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertNotIn("tc-required", rules)
        self.assertNotIn("tc-sections", rules)
        self.assertNotIn("tc-schema", rules)

    def test_group_with_string_children_flagged_by_schema(self):
        # children como string (no lista) lo caza el schema (rama group) o la regla de grupo.
        g = _group_fixture()
        txt = g.read_text(encoding="utf-8").replace("children:\n  - child.md\n", 'children: "child.md"\n')
        g.write_text(txt, encoding="utf-8")
        try:
            rules = {f["rule"] for f in tc_lint.lint(g) if f["level"] == "error"}
        finally:
            shutil.rmtree(g.parent, ignore_errors=True)
        self.assertTrue({"tc-schema", "tc-group-children"} & rules, msg=str(rules))


class TestTestsAssert(unittest.TestCase):
    """tc-tests-assert: un test congelado (Python) sin ninguna aserción es un oráculo vacío."""

    def _rules(self, test_body, lang=None):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "t.py").write_text(test_body, encoding="utf-8")
            fm = '---\ntask: f\nsignature: "def f(x)"\ntests: t.py\n'
            fm += f"language: {lang}\n" if lang else ""
            fm += "---\n## Intent\nx\n"
            (d / "c.md").write_text(fm, encoding="utf-8")
            return {x["rule"] for x in tc_lint.lint(d / "c.md")}
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_assert_flagged(self):
        self.assertIn("tc-tests-assert", self._rules("def test_f():\n    f(1)\n"))

    def test_plain_assert_ok(self):
        self.assertNotIn("tc-tests-assert", self._rules("def test_f():\n    assert f(1) == 1\n"))

    def test_unittest_assert_ok(self):
        body = "import unittest\nclass T(unittest.TestCase):\n    def t(self):\n        self.assertEqual(f(1), 1)\n"
        self.assertNotIn("tc-tests-assert", self._rules(body))

    def test_non_python_skipped(self):
        # JS: las aserciones tienen otra forma; la regla se omite (no falso positivo).
        self.assertNotIn("tc-tests-assert", self._rules("f(1)\n", lang="javascript"))


class TestRepoRootPathFallback(unittest.TestCase):
    """resolve_contract_path: si target/tests no existen relativos al directorio del contrato,
    cae a resolverlos relativos a la raiz del repo (ancestro mas cercano con `.git`). Soporta
    contratos que declaran target/tests relativos a la raiz del proyecto (convencion de
    KDD-template's validate_contracts.py) en vez de relativos al propio contrato con `../..`
    (convencion nativa de este gate) -- sin romper NUNCA la resolucion historica."""

    def _repo(self):
        d = Path(tempfile.mkdtemp())
        (d / ".git").mkdir()
        (d / "knowledge" / "contracts").mkdir(parents=True)
        return d

    def test_prefers_contract_relative_when_it_exists(self):
        d = self._repo()
        try:
            contract_dir = d / "knowledge" / "contracts"
            (contract_dir / "local.py").write_text("x", encoding="utf-8")
            (d / "local.py").write_text("y", encoding="utf-8")  # tambien existe en la raiz
            got = tc_lint.resolve_contract_path(contract_dir, "local.py")
            self.assertEqual(got, contract_dir / "local.py")  # gana SIEMPRE contract-relative
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_falls_back_to_repo_root_when_contract_relative_missing(self):
        d = self._repo()
        try:
            contract_dir = d / "knowledge" / "contracts"
            (d / "src").mkdir()
            (d / "src" / "impl.py").write_text("x", encoding="utf-8")
            got = tc_lint.resolve_contract_path(contract_dir, "src/impl.py")
            self.assertEqual(got.resolve(), (d / "src" / "impl.py").resolve())
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_returns_original_when_neither_exists(self):
        d = self._repo()
        try:
            contract_dir = d / "knowledge" / "contracts"
            got = tc_lint.resolve_contract_path(contract_dir, "nope.py")
            self.assertEqual(got, contract_dir / "nope.py")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_repo_root_found_returns_original(self):
        d = Path(tempfile.mkdtemp())  # sin .git en ningun ancestro conocido -- no debe reventar
        try:
            got = tc_lint.resolve_contract_path(d, "nope.py")
            self.assertEqual(got, d / "nope.py")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_r_tests_frozen_passes_with_repo_root_relative_tests(self):
        d = self._repo()
        try:
            contract_dir = d / "knowledge" / "contracts"
            (d / "tests").mkdir()
            (d / "tests" / "test_impl.py").write_text(
                "def test_f():\n    assert f(1) == 1\n", encoding="utf-8")
            fm = ('---\ntask: f\nsignature: "def f(x)"\ntests: tests/test_impl.py\n---\n'
                  '## Intent\nx\n')
            contract = contract_dir / "c.md"
            contract.write_text(fm, encoding="utf-8")
            rules = {x["rule"] for x in tc_lint.lint(contract)}
            self.assertNotIn("tc-tests-frozen", rules)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_task_gate_pass_with_repo_root_relative_target_and_tests(self):
        """End-to-end: contrato con target/tests relativos a la RAIZ del repo (convencion
        KDD-template), no al directorio del contrato -- pasa task_gate.gate() completo via el
        fallback a raiz del repo (deteccion por `.git` ancestro)."""
        d = self._repo()
        try:
            contract_dir = d / "knowledge" / "contracts"
            (d / "src").mkdir()
            (d / "tests").mkdir()
            (d / "src" / "impl.py").write_text(
                "def add_one(x: int) -> int:\n    return x + 1\n", encoding="utf-8")
            (d / "tests" / "test_impl.py").write_text(
                "import unittest, sys, os\n"
                "sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))\n"
                "from impl import add_one\n"
                "class T(unittest.TestCase):\n"
                "    def test_it(self):\n"
                "        self.assertEqual(add_one(1), 2)\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                encoding="utf-8")
            fm = (
                '---\n'
                'task: add-one\n'
                'intent: "Sumar uno a un entero."\n'
                'target: src/impl.py\n'
                'signature: "def add_one(x: int) -> int"\n'
                'test_command: "python tests/test_impl.py"\n'
                'test_cwd: ../..\n'
                'budget: { cyclomatic_max: 5, nesting_max: 2, params_max: 1, lines_max: 10 }\n'
                'tests: tests/test_impl.py\n'
                'deps_allowed: []\n'
                'forbids: [network, subprocess, llm]\n'
                '---\n'
                '## Intent\nx\n## Interface\n```\ndef add_one(x: int) -> int\n```\n'
                '## Invariants\n- siempre suma 1\n'
                '## Examples\n- add_one(1) -> 2\n- add_one(0) -> 1\n'
                "## Do / Don't\n- DO: nada especial\n"
                '## Tests\nver tests/test_impl.py\n'
                '## Constraints\n- PARAR si necesita red\n'
            )
            contract = contract_dir / "add-one.md"
            contract.write_text(fm, encoding="utf-8")
            v = task_gate.gate(str(contract))
            self.assertEqual(v["verdict"], "PASS", msg=v)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
