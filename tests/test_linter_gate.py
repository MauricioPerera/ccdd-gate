"""test_linter_gate.py — tests de linter_gate (linters externos deterministas como checks opt-in).

Sin LLM. (a) Unit sobre normalizacion y politicas inyectando un runner fake (version mismatch,
ausente+required, ausente+no-required, findings, limpio, config invalida, glob vacio).
(b) Integracion REAL con ruff: tempdir con F401 -> exit 1; arreglado -> exit 0; mismatch -> exit 2.
Los de integracion saltan limpios (skipUnless) si ruff no esta o su version != pin del test.

Misma estructura para clippy (adaptador crate-completo, no por-archivo: ver ClippyAdapter)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import linter_gate as lg  # noqa: E402

RUFF_PIN = "0.15.20"  # pin del example; coincide con el ruff instalado en este entorno


def _installed_ruff():
    """Version instalada de ruff, o None si no esta (subprocess real, sin mock)."""
    import subprocess
    try:
        out = subprocess.run(["ruff", "--version"], capture_output=True, encoding="utf-8")
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    parts = out.stdout.strip().split()
    return parts[1] if len(parts) >= 2 else out.stdout.strip()


_INSTALLED = _installed_ruff()
_HAS_RUFF = _INSTALLED == RUFF_PIN


class FakeRunner:
    """Runner inyectable: despacha `ruff --version` y `ruff check ...` con respuestas enlatadas."""
    def __init__(self, version=RUFF_PIN, not_installed=False,
                 check_json="[]", check_rc=0, check_raises=None):
        self.version = version
        self.not_installed = not_installed
        self.check_json = check_json
        self.check_rc = check_rc
        self.check_raises = check_raises
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), cwd))
        if args[:2] == ["ruff", "--version"]:
            if self.not_installed:
                raise FileNotFoundError("ruff")
            return 0, f"ruff {self.version}\n", ""
        if self.check_raises is not None:
            raise self.check_raises
        return self.check_rc, self.check_json, ""


def _write_cfg(d, entries):
    """Escribe entries (list[dict]) como linters.yaml en tempdir d; devuelve path str."""
    import yaml
    p = d / "linters.yaml"
    p.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return str(p)


# --- Ruff JSON enlatado (forma real de `ruff check --output-format json`) ---
RUFF_JSON_F401 = """[
  {"filename": "%(root)s/bad.py", "code": "F401", "location": {"row": 1, "column": 8},
   "message": "`os` imported but unused", "name": "unused-import"},
  {"filename": "%(root)s/other.py", "code": "F401", "location": {"row": 2, "column": 8},
   "message": "`sys` imported but unused", "name": "unused-import"}
]"""


class Normalize(unittest.TestCase):
    def test_normalize_basic_and_sorted(self):
        root = "D:/proj"
        data = [
            {"filename": f"{root}/b.py", "code": "F401", "location": {"row": 2},
             "message": "b unused"},
            {"filename": f"{root}/a.py", "code": "E501", "location": {"row": 5},
             "message": "line too long"},
            {"filename": f"{root}/a.py", "code": "F401", "location": {"row": 1},
             "message": "a unused"},
        ]
        got = lg.RuffAdapter()._normalize(data, root)
        self.assertEqual(got, [
            {"file": "a.py", "line": 1, "code": "F401", "msg": "a unused"},
            {"file": "a.py", "line": 5, "code": "E501", "msg": "line too long"},
            {"file": "b.py", "line": 2, "code": "F401", "msg": "b unused"},
        ])

    def test_normalize_uses_forward_slashes(self):
        data = [{"filename": "C:/repo/src/x/y.py", "code": "F401",
                 "location": {"row": 3}, "message": "m"}]
        got = lg.RuffAdapter()._normalize(data, "C:/repo")
        self.assertEqual(got[0]["file"], "src/x/y.py")
        self.assertNotIn("\\", got[0]["file"])

    def test_normalize_empty(self):
        self.assertEqual(lg.RuffAdapter()._normalize([], "."), [])

    def test_normalize_outside_root_falls_back(self):
        data = [{"filename": "C:/elsewhere/x.py", "code": "F401",
                 "location": {"row": 1}, "message": "m"}]
        got = lg.RuffAdapter()._normalize(data, "D:/repo")
        self.assertEqual(got[0]["file"], "C:/elsewhere/x.py")


class PoliciesUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_version_mismatch_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN}])
        runner = FakeRunner(version="0.99.0")  # instalada 0.99.0 != pin
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("0.99.0", payload["error"])
        self.assertIn(RUFF_PIN, payload["error"])

    def test_ausente_required_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN, "required": True}])
        runner = FakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("no instalada", payload["error"])

    def test_ausente_not_required_skip_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN, "required": False}])
        runner = FakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["skipped"], True)
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_findings_exit1(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN}])
        js = RUFF_JSON_F401 % {"root": str(self.root).replace("\\", "/")}
        runner = FakeRunner(version=RUFF_PIN, check_json=js, check_rc=1)
        # crear los archivos para que el glob los encuentre
        (self.root / "bad.py").write_text("import os\n", encoding="utf-8")
        (self.root / "other.py").write_text("import sys\n", encoding="utf-8")
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["results"][0]["findings"]), 2)
        self.assertEqual(payload["results"][0]["findings"][0]["code"], "F401")

    def test_clean_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN}])
        (self.root / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        runner = FakeRunner(version=RUFF_PIN, check_json="[]", check_rc=0)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"], [])
        self.assertNotIn("skipped", payload["results"][0])

    def test_glob_empty_clean_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN, "files": "src/**/*.py"}])
        runner = FakeRunner(version=RUFF_PIN)  # no deberia invocarse el check
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["findings"], [])
        # solo se llamo a --version, nunca a `ruff check`
        self.assertTrue(all(c[0][:2] == ["ruff", "--version"] for c in runner.calls))

    def test_tool_crash_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": RUFF_PIN}])
        (self.root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        runner = FakeRunner(version=RUFF_PIN, check_rc=2, check_json="")
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("ruff falló", payload["error"])


class ConfigValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_not_a_list_exit2(self):
        cfg = _write_cfg(self.root, {"tool": "ruff", "version": RUFF_PIN})
        code, payload = lg.gate(cfg, str(self.root), runner=FakeRunner())
        self.assertEqual(code, 2)
        self.assertIn("lista", payload["error"])

    def test_missing_version_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "files": "**/*.py"}])
        code, _ = lg.gate(cfg, str(self.root), runner=FakeRunner())
        self.assertEqual(code, 2)

    def test_unknown_tool_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "eslint", "version": "1.0"}])
        code, payload = lg.gate(cfg, str(self.root), runner=FakeRunner())
        self.assertEqual(code, 2)
        self.assertIn("eslint", payload["error"])

    def test_empty_version_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "ruff", "version": ""}])
        code, _ = lg.gate(cfg, str(self.root), runner=FakeRunner())
        self.assertEqual(code, 2)


@unittest.skipUnless(_HAS_RUFF, f"ruff {RUFF_PIN} no instalada (instalada: {_INSTALLED})")
class IntegrationRealRuff(unittest.TestCase):
    """Integracion REAL con ruff (runner por defecto = subprocess). Corre solo si ruff==pin."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, **overrides):
        entry = {"tool": "ruff", "version": RUFF_PIN, "files": "**/*.py"}
        entry.update(overrides)
        return _write_cfg(self.root, [entry])

    def test_f401_exit1_with_normalized_finding(self):
        (self.root / "bad.py").write_text("import os\n\ndef foo():\n    return 1\n",
                                          encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        findings = payload["results"][0]["findings"]
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["file"], "bad.py")
        self.assertEqual(f["code"], "F401")
        self.assertEqual(f["line"], 1)
        self.assertIn("os", f["msg"])

    def test_clean_exit0(self):
        (self.root / "ok.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_version_mismatch_real_exit2(self):
        (self.root / "ok.py").write_text("x = 1\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(version="0.0.0"), str(self.root))
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertIn("entorno inválido", payload["error"])


# --- clippy: mismo contrato que ruff, pero el adaptador linta el crate COMPLETO (no archivos
# sueltos como input) y usa `files` solo para skip-si-vacio + post-filtro de findings. ---

def _installed_clippy():
    """Version instalada de clippy, o None si cargo/clippy no esta (subprocess real, sin mock)."""
    try:
        out = subprocess.run(["cargo", "clippy", "--version"], capture_output=True, encoding="utf-8")
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    parts = out.stdout.strip().split()
    return parts[1] if len(parts) >= 2 else out.stdout.strip()


_INSTALLED_CLIPPY = _installed_clippy()  # pin = lo instalado; sin cargo, integracion salta
CLIPPY_PIN = _INSTALLED_CLIPPY or "0.0.0"
_HAS_CLIPPY = _INSTALLED_CLIPPY is not None


class ClippyFakeRunner:
    """Runner inyectable: despacha `cargo clippy --version` y `cargo clippy --message-format=json`."""
    def __init__(self, version=CLIPPY_PIN, not_installed=False, jsonl="", rc=0):
        self.version = version
        self.not_installed = not_installed
        self.jsonl = jsonl
        self.rc = rc
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), cwd))
        if args[:3] == ["cargo", "clippy", "--version"]:
            if self.not_installed:
                raise FileNotFoundError("cargo")
            return 0, f"clippy {self.version} (abc 2026-01-01)\n", ""
        return self.rc, self.jsonl, ""


def _clippy_msg(file_name, line, code, message, level="warning"):
    """Una linea JSON `reason: compiler-message` como la emite `cargo --message-format=json`."""
    return json.dumps({
        "reason": "compiler-message",
        "message": {
            "level": level, "message": message, "code": {"code": code},
            "spans": [{"file_name": file_name, "line_start": line, "is_primary": True}],
        },
    })


CLIPPY_NOISE_LINES = "\n".join([
    json.dumps({"reason": "compiler-artifact"}),
    json.dumps({"reason": "build-finished", "success": True}),
    json.dumps({  # resumen sin codigo de lint -- no debe contarse como finding
        "reason": "compiler-message",
        "message": {"level": "warning", "message": "1 warning emitted", "code": None, "spans": []},
    }),
])


class ClippyNormalize(unittest.TestCase):
    def test_parse_and_normalize_sorted_and_filtered(self):
        jsonl = "\n".join([
            _clippy_msg("src/b.rs", 2, "clippy::foo", "b lint"),
            _clippy_msg("src/a.rs", 5, "clippy::bar", "a lint late"),
            _clippy_msg("src/a.rs", 1, "clippy::foo", "a lint early"),
            CLIPPY_NOISE_LINES,
        ])
        adapter = lg.ClippyAdapter()
        diagnostics = adapter._parse_messages(jsonl)
        self.assertEqual(len(diagnostics), 3)  # el resumen sin codigo quedo afuera
        got = adapter._normalize(diagnostics, ".", allowed=set())
        self.assertEqual(got, [
            {"file": "src/a.rs", "line": 1, "code": "clippy::foo", "msg": "a lint early"},
            {"file": "src/a.rs", "line": 5, "code": "clippy::bar", "msg": "a lint late"},
            {"file": "src/b.rs", "line": 2, "code": "clippy::foo", "msg": "b lint"},
        ])

    def test_normalize_windows_backslash_path(self):
        diagnostics = [json.loads(_clippy_msg("src\\main.rs", 7, "clippy::len_zero", "m"))["message"]]
        got = lg.ClippyAdapter()._normalize(diagnostics, ".", allowed=set())
        self.assertEqual(got[0]["file"], "src/main.rs")

    def test_normalize_filters_to_allowed(self):
        diagnostics = [
            json.loads(_clippy_msg("crates/a/src/lib.rs", 1, "clippy::foo", "m"))["message"],
            json.loads(_clippy_msg("crates/b/src/lib.rs", 1, "clippy::foo", "m"))["message"],
        ]
        got = lg.ClippyAdapter()._normalize(diagnostics, ".", allowed={"crates/a/src/lib.rs"})
        self.assertEqual([f["file"] for f in got], ["crates/a/src/lib.rs"])

    def test_normalize_empty_allowed_means_no_filter(self):
        diagnostics = [json.loads(_clippy_msg("x.rs", 1, "clippy::foo", "m"))["message"]]
        got = lg.ClippyAdapter()._normalize(diagnostics, ".", allowed=set())
        self.assertEqual(len(got), 1)


class ClippyPoliciesUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_files_is_rs_glob(self):
        # sin `files` en la entrada, el default de ClippyAdapter (no el de ruff) debe aplicarse.
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        entries, err = lg._load_linters(cfg)
        self.assertIsNone(err)
        self.assertEqual(entries[0]["files"], "**/*.rs")

    def test_version_mismatch_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        runner = ClippyFakeRunner(version="0.0.1")
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("0.0.1", payload["error"])
        self.assertIn(CLIPPY_PIN, payload["error"])

    def test_ausente_required_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN, "required": True}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        runner = ClippyFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("no instalada", payload["error"])

    def test_ausente_not_required_skip_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN, "required": False}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        runner = ClippyFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["skipped"], True)

    def test_findings_exit1(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        jsonl = _clippy_msg("src/main.rs", 1, "clippy::len_zero", "length comparison to zero")
        runner = ClippyFakeRunner(jsonl=jsonl, rc=0)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"][0]["code"], "clippy::len_zero")

    def test_findings_exit1_even_with_rc_101(self):
        # cargo clippy con -D warnings sale con 101 aunque el problema sea "solo" un lint
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        jsonl = _clippy_msg("src/main.rs", 1, "clippy::len_zero", "length comparison to zero")
        runner = ClippyFakeRunner(jsonl=jsonl, rc=101)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)

    def test_clean_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        runner = ClippyFakeRunner(jsonl=CLIPPY_NOISE_LINES, rc=0)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_glob_empty_clean_exit0_never_invokes_cargo(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        # sin archivos .rs en el tempdir
        runner = ClippyFakeRunner()
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(all(c[0][:3] == ["cargo", "clippy", "--version"] for c in runner.calls))

    def test_tool_crash_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": CLIPPY_PIN}])
        (self.root / "src").mkdir()
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        runner = ClippyFakeRunner(rc=1, jsonl="not json at all")  # 1 no esta en (0, 101)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("cargo clippy falló", payload["error"])


@unittest.skipUnless(_HAS_CLIPPY, "cargo clippy no disponible (cargo/clippy no instalados)")
class IntegrationRealClippy(unittest.TestCase):
    """Integracion REAL con `cargo clippy` sobre un crate minimo generado con `cargo new`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        # tempfile.mkdtemp() ya crea el directorio -> `cargo new` lo rechaza ("already exists");
        # `cargo init` si opera sobre un directorio existente vacio.
        subprocess.run(["cargo", "init", "--quiet", "--name", "sample", "."],
                        capture_output=True, encoding="utf-8", cwd=str(self.root))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, **overrides):
        entry = {"tool": "clippy", "version": CLIPPY_PIN, "files": "src/**/*.rs"}
        entry.update(overrides)
        return _write_cfg(self.root, [entry])

    def test_len_zero_exit1_with_normalized_finding(self):
        (self.root / "src" / "main.rs").write_text(
            "fn main() {\n    let v: Vec<i32> = Vec::new();\n"
            "    if v.len() == 0 {\n        println!(\"empty\");\n    }\n}\n",
            encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 1)
        findings = payload["results"][0]["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "src/main.rs")
        self.assertEqual(findings[0]["code"], "clippy::len_zero")

    def test_clean_exit0(self):
        (self.root / "src" / "main.rs").write_text(
            "fn main() {\n    let v: Vec<i32> = Vec::new();\n"
            "    if v.is_empty() {\n        println!(\"empty\");\n    }\n}\n",
            encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_version_mismatch_real_exit2(self):
        (self.root / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(version="0.0.0"), str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("entorno inválido", payload["error"])


# --- govet: mismo contrato que clippy (linta el MODULO/PAQUETE COMPLETO, no archivos sueltos
# como input). `files` solo para skip-si-vacio + post-filtro. Salida en stderr, una linea por
# hallazgo `path:line:col: msg`; sin codigos de regla -> code="govet". ---

def _installed_go():
    """Version instalada de go, o None si go no esta (subprocess real, sin mock)."""
    try:
        out = subprocess.run(["go", "version"], capture_output=True, encoding="utf-8")
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    # "go version go1.26.4 windows/amd64" -> 3er token = "go1.26.4"
    parts = out.stdout.strip().split()
    return parts[2] if len(parts) >= 3 else out.stdout.strip()


_INSTALLED_GO = _installed_go()  # pin = lo instalado; sin go, integracion salta
GOVET_PIN = _INSTALLED_GO or "go0.0.0"
_HAS_GO = _INSTALLED_GO is not None


class GoVetFakeRunner:
    """Runner inyectable: despacha `go version` y `go vet ./...` (findings en stderr)."""
    def __init__(self, version=GOVET_PIN, not_installed=False, vet_stderr="", rc=0):
        self.version = version
        self.not_installed = not_installed
        self.vet_stderr = vet_stderr
        self.rc = rc
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), cwd))
        if args[:2] == ["go", "version"]:
            if self.not_installed:
                raise FileNotFoundError("go")
            return 0, f"go version {self.version} windows/amd64\n", ""
        return self.rc, "", self.vet_stderr


class GoVetNormalize(unittest.TestCase):
    def test_parse_and_normalize_sorted(self):
        stderr = "\n".join([
            "main.go:6:14: fmt.Printf format %d has arg \"not a number\" of wrong type string",
            "pkgb\\pkgb.go:6:14: b lint",
            "other.go:1:2: a lint early",
        ])
        adapter = lg.GoVetAdapter()
        msgs = adapter._parse_messages(stderr)
        self.assertEqual(len(msgs), 3)
        got = adapter._normalize(msgs, ".", allowed=set())
        self.assertEqual(got, [
            {"file": "main.go", "line": 6, "code": "govet",
             "msg": "fmt.Printf format %d has arg \"not a number\" of wrong type string"},
            {"file": "other.go", "line": 1, "code": "govet", "msg": "a lint early"},
            {"file": "pkgb/pkgb.go", "line": 6, "code": "govet", "msg": "b lint"},
        ])

    def test_non_matching_line_ignored(self):
        # encabezados de paquete / lineas raras que no matchean el patron -> ignoradas
        stderr = "\n".join([
            "# example.com/probe",
            "# [example.com/probe]",
            "main.go:6:14: real finding here",
        ])
        adapter = lg.GoVetAdapter()
        msgs = adapter._parse_messages(stderr)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["file"], "main.go")
        self.assertEqual(msgs[0]["line"], 6)

    def test_windows_backslash_normalized(self):
        msgs = lg.GoVetAdapter()._parse_messages("pkgb\\pkgb.go:6:14: m")
        self.assertEqual(msgs[0]["file"], "pkgb/pkgb.go")
        self.assertNotIn("\\", msgs[0]["file"])

    def test_dot_slash_prefix_stripped(self):
        # Go < 1.25 prefija la ruta con `./` (Linux) o `.\` (Windows): `./main.go:6:2:`.
        # El glob de `files` da paths relativos SIN prefijo (`main.go`), asi que hay que
        # strippearlo o el finding se filtra contra `allowed` y se pierde (gate -> code 0).
        adapter = lg.GoVetAdapter()
        for stderr in (
            "./main.go:6:2: fmt.Printf format %d has arg x of wrong type string",
            ".\\main.go:6:2: fmt.Printf format %d has arg x of wrong type string",
            "./pkgb/pkgb.go:6:2: copylocks: foo",
        ):
            msgs = adapter._parse_messages(stderr)
            self.assertEqual(len(msgs), 1, stderr)
            self.assertFalse(msgs[0]["file"].startswith("./"), stderr)
            self.assertNotIn("\\", msgs[0]["file"], stderr)
        self.assertEqual(adapter._parse_messages("./main.go:6:2: m")[0]["file"], "main.go")
        self.assertEqual(adapter._parse_messages("./pkgb/pkgb.go:6:2: m")[0]["file"],
                         "pkgb/pkgb.go")

    def test_normalize_filters_to_allowed(self):
        msgs = lg.GoVetAdapter()._parse_messages("\n".join([
            "a/a.go:1:1: m",
            "b/b.go:1:1: m",
        ]))
        got = lg.GoVetAdapter()._normalize(msgs, ".", allowed={"a/a.go"})
        self.assertEqual([f["file"] for f in got], ["a/a.go"])

    def test_normalize_empty_allowed_means_no_filter(self):
        msgs = lg.GoVetAdapter()._parse_messages("x.go:1:1: m")
        got = lg.GoVetAdapter()._normalize(msgs, ".", allowed=set())
        self.assertEqual(len(got), 1)

    def test_parse_empty(self):
        self.assertEqual(lg.GoVetAdapter()._parse_messages(""), [])
        self.assertEqual(lg.GoVetAdapter()._parse_messages(None), [])

    def test_code_is_constant_govet(self):
        msgs = lg.GoVetAdapter()._parse_messages("x.go:1:1: m")
        got = lg.GoVetAdapter()._normalize(msgs, ".", allowed=set())
        self.assertEqual(got[0]["code"], "govet")


class GoVetPoliciesUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_files_is_go_glob(self):
        # sin `files` en la entrada, el default de GoVetAdapter debe aplicarse.
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        entries, err = lg._load_linters(cfg)
        self.assertIsNone(err)
        self.assertEqual(entries[0]["files"], "**/*.go")

    def test_version_mismatch_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(version="go0.0.1")
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("go0.0.1", payload["error"])
        self.assertIn(GOVET_PIN, payload["error"])

    def test_ausente_required_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN, "required": True}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("no instalada", payload["error"])

    def test_ausente_not_required_skip_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN, "required": False}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["skipped"], True)

    def test_findings_exit1(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        stderr = 'main.go:6:14: fmt.Printf format %d has arg "not a number" of wrong type string\n'
        runner = GoVetFakeRunner(vet_stderr=stderr, rc=1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        f = payload["results"][0]["findings"][0]
        self.assertEqual(f["code"], "govet")
        self.assertEqual(f["file"], "main.go")
        self.assertEqual(f["line"], 6)

    def test_findings_exit1_dot_slash_prefix_survives_filter(self):
        # Regresion del fallo de CI: en Go < 1.25 `go vet` reporta la ruta con prefijo `./`
        # (Linux) / `.\` (Windows): `./main.go:6:2:`. Como el glob `**/*.go` expande a paths
        # relativos SIN prefijo (`main.go`), el finding se filtraba contra `allowed` y se
        # perdia -> gate devolvia code 0 pese a haber hallazgo. El adapter debe strippear el
        # prefijo para que el finding sobreviva en cualquier version de Go.
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN, "files": "**/*.go"}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        stderr = './main.go:6:2: fmt.Printf format %d has arg "not a number" of wrong type string\n'
        runner = GoVetFakeRunner(vet_stderr=stderr, rc=1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        findings = payload["results"][0]["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["file"], "main.go")
        self.assertEqual(findings[0]["line"], 6)
        self.assertEqual(findings[0]["code"], "govet")

    def test_findings_exit1_backslash_dot_prefix_survives_filter(self):
        # Idem anterior pero con el prefijo `.\` que emite Go < 1.25 en Windows.
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN, "files": "**/*.go"}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        stderr = '.\\main.go:6:2: fmt.Printf format %d has arg "not a number" of wrong type string\n'
        runner = GoVetFakeRunner(vet_stderr=stderr, rc=1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        f = payload["results"][0]["findings"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["file"], "main.go")
        self.assertEqual(f[0]["line"], 6)

    def test_clean_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(vet_stderr="", rc=0)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_glob_empty_clean_exit0_never_invokes_go_vet(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        # sin archivos .go en el tempdir -> solo se llama a `go version`, nunca a `go vet`
        runner = GoVetFakeRunner()
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(all(c[0][:2] == ["go", "version"] for c in runner.calls))

    def test_tool_crash_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(rc=2, vet_stderr="go: boom")  # 2 no esta en (0, 1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("go vet falló", payload["error"])

    def test_uses_args_when_provided(self):
        cfg = _write_cfg(self.root, [{"tool": "govet", "version": GOVET_PIN, "args": ["./..."]}])
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        runner = GoVetFakeRunner(vet_stderr="", rc=0)
        lg.gate(cfg, str(self.root), runner=runner)
        vet_calls = [c for c in runner.calls if c[0][:2] == ["go", "vet"]]
        self.assertEqual(vet_calls[0][0], ["go", "vet", "./..."])


@unittest.skipUnless(_HAS_GO, "go no disponible (toolchain de Go no instalado)")
class IntegrationRealGoVet(unittest.TestCase):
    """Integracion REAL con `go vet` sobre un modulo minimo generado con `go mod init`."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        # `go mod init` opera sobre un directorio existente (a diferencia de `cargo new`).
        subprocess.run(["go", "mod", "init", "example.com/probe"],
                       capture_output=True, encoding="utf-8", cwd=str(self.root))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, **overrides):
        entry = {"tool": "govet", "version": GOVET_PIN, "files": "**/*.go"}
        entry.update(overrides)
        return _write_cfg(self.root, [entry])

    def test_printf_wrong_type_exit1_with_normalized_finding(self):
        (self.root / "main.go").write_text(
            "package main\n\nimport \"fmt\"\n\nfunc main() {\n"
            "\tfmt.Printf(\"%d\\n\", \"not a number\")\n}\n",
            encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        findings = payload["results"][0]["findings"]
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["file"], "main.go")
        self.assertEqual(f["code"], "govet")
        self.assertEqual(f["line"], 6)
        self.assertIn("Printf", f["msg"])

    def test_clean_exit0(self):
        (self.root / "main.go").write_text(
            "package main\n\nimport \"fmt\"\n\nfunc main() {\n"
            "\tfmt.Printf(\"%d\\n\", 5)\n}\n",
            encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_version_mismatch_real_exit2(self):
        (self.root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(version="go0.0.0"), str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("entorno inválido", payload["error"])


# --- sqlfluff: por-archivo como ruff (acepta una LISTA de archivos como input y lints varios en
# una sola invocacion), NO de modulo completo como clippy/govet. Salida JSON anidada: lista con un
# item POR ARCHIVO {filepath, violations:[...]}; cada violation tiene su propio `code` (LT09, ...).
# El dialecto SQL se declara via `args: ["--dialect", "postgres"]` en la config YAML. ---

def _installed_sqlfluff():
    """Version instalada de sqlfluff, o None si no esta (subprocess real, sin mock)."""
    try:
        out = subprocess.run(["sqlfluff", "--version"], capture_output=True, encoding="utf-8")
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    # "sqlfluff, version 4.2.2" -> ultimo token = "4.2.2"
    parts = out.stdout.strip().split()
    return parts[-1] if parts else out.stdout.strip()


_INSTALLED_SQLFLUFF = _installed_sqlfluff()  # pin = lo instalado; sin sqlfluff, integracion salta
SQLFLUFF_PIN = _INSTALLED_SQLFLUFF or "0.0.0"
_HAS_SQLFLUFF = _INSTALLED_SQLFLUFF is not None


class SqlfluffFakeRunner:
    """Runner inyectable: despacha `sqlfluff --version` y `sqlfluff lint ... --format json`."""
    def __init__(self, version=SQLFLUFF_PIN, not_installed=False, lint_json="[]", lint_rc=0,
                 lint_raises=None):
        self.version = version
        self.not_installed = not_installed
        self.lint_json = lint_json
        self.lint_rc = lint_rc
        self.lint_raises = lint_raises
        self.calls = []

    def __call__(self, args, cwd):
        self.calls.append((list(args), cwd))
        if args[:2] == ["sqlfluff", "--version"]:
            if self.not_installed:
                raise FileNotFoundError("sqlfluff")
            return 0, f"sqlfluff, version {self.version}\n", ""
        if self.lint_raises is not None:
            raise self.lint_raises
        return self.lint_rc, self.lint_json, ""


def _sqlfluff_violation(line, code, description):
    """Una violation como las que anida sqlfluff dentro de cada archivo (campos que importan)."""
    return {"start_line_no": line, "start_line_pos": 1, "code": code,
            "description": description, "name": "layout.dummy", "warning": False, "fixes": []}


def _sqlfluff_file(filepath, violations):
    """Un item de la lista externa que devuelve `sqlfluff lint --format json`."""
    return {"filepath": filepath, "violations": violations,
            "statistics": {}, "timings": {}}


class SqlfluffNormalize(unittest.TestCase):
    def test_normalize_basic_and_sorted(self):
        # un archivo con 2 violaciones + multiples archivos en una sola respuesta; orden por
        # (file, line, code); forward-slash.
        root = "D:/proj"
        data = [
            _sqlfluff_file(f"{root}/b.sql", [
                _sqlfluff_violation(2, "LT01", "b spacing"),
            ]),
            _sqlfluff_file(f"{root}/a.sql", [
                _sqlfluff_violation(5, "LT01", "a spacing late"),
                _sqlfluff_violation(1, "LT09", "a targets"),
            ]),
        ]
        got = lg.SqlfluffAdapter()._normalize(data, root)
        self.assertEqual(got, [
            {"file": "a.sql", "line": 1, "code": "LT09", "msg": "a targets"},
            {"file": "a.sql", "line": 5, "code": "LT01", "msg": "a spacing late"},
            {"file": "b.sql", "line": 2, "code": "LT01", "msg": "b spacing"},
        ])

    def test_normalize_uses_forward_slashes(self):
        data = [_sqlfluff_file("C:/repo/src/x/y.sql", [_sqlfluff_violation(3, "LT01", "m")])]
        got = lg.SqlfluffAdapter()._normalize(data, "C:/repo")
        self.assertEqual(got[0]["file"], "src/x/y.sql")
        self.assertNotIn("\\", got[0]["file"])

    def test_normalize_empty_violations_no_findings(self):
        # un archivo con violations: [] no genera findings (sigue apareciendo el item, pero vacio)
        data = [_sqlfluff_file("D:/proj/clean.sql", [])]
        self.assertEqual(lg.SqlfluffAdapter()._normalize(data, "D:/proj"), [])

    def test_normalize_empty(self):
        self.assertEqual(lg.SqlfluffAdapter()._normalize([], "."), [])

    def test_normalize_outside_root_falls_back(self):
        data = [_sqlfluff_file("C:/elsewhere/x.sql", [_sqlfluff_violation(1, "LT01", "m")])]
        got = lg.SqlfluffAdapter()._normalize(data, "D:/repo")
        self.assertEqual(got[0]["file"], "C:/elsewhere/x.sql")


class SqlfluffPoliciesUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_default_files_is_sql_glob(self):
        # sin `files` en la entrada, el default de SqlfluffAdapter debe aplicarse.
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN}])
        entries, err = lg._load_linters(cfg)
        self.assertIsNone(err)
        self.assertEqual(entries[0]["files"], "**/*.sql")

    def test_version_mismatch_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN}])
        (self.root / "bad.sql").write_text("select 1\n", encoding="utf-8")
        runner = SqlfluffFakeRunner(version="0.0.1")  # instalada 0.0.1 != pin
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("0.0.1", payload["error"])
        self.assertIn(SQLFLUFF_PIN, payload["error"])

    def test_ausente_required_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN, "required": True}])
        (self.root / "bad.sql").write_text("select 1\n", encoding="utf-8")
        runner = SqlfluffFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("no instalada", payload["error"])

    def test_ausente_not_required_skip_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN, "required": False}])
        (self.root / "bad.sql").write_text("select 1\n", encoding="utf-8")
        runner = SqlfluffFakeRunner(not_installed=True)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["skipped"], True)
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_findings_exit1(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN,
                                      "args": ["--dialect", "postgres"]}])
        (self.root / "bad.sql").write_text("select id,name from users where id=1\n", encoding="utf-8")
        js = json.dumps([_sqlfluff_file(
            f"{self.root.as_posix()}/bad.sql",
            [_sqlfluff_violation(1, "LT09", "Select targets should be on a new line.")])])
        runner = SqlfluffFakeRunner(lint_json=js, lint_rc=1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        findings = payload["results"][0]["findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["code"], "LT09")
        self.assertEqual(findings[0]["file"], "bad.sql")
        self.assertEqual(findings[0]["line"], 1)

    def test_clean_exit0(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN,
                                      "args": ["--dialect", "postgres"]}])
        (self.root / "ok.sql").write_text("SELECT\n    id\nFROM users\n", encoding="utf-8")
        js = json.dumps([_sqlfluff_file(f"{self.root.as_posix()}/ok.sql", [])])
        runner = SqlfluffFakeRunner(lint_json=js, lint_rc=0)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"], [])
        self.assertNotIn("skipped", payload["results"][0])

    def test_glob_empty_clean_exit0_never_invokes_lint(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN,
                                      "files": "src/**/*.sql"}])
        runner = SqlfluffFakeRunner()  # no deberia invocarse el lint
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 0)
        self.assertEqual(payload["results"][0]["findings"], [])
        # solo se llamo a --version, nunca a `sqlfluff lint`
        self.assertTrue(all(c[0][:2] == ["sqlfluff", "--version"] for c in runner.calls))

    def test_tool_crash_exit2(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN,
                                      "args": ["--dialect", "postgres"]}])
        (self.root / "bad.sql").write_text("select 1\n", encoding="utf-8")
        runner = SqlfluffFakeRunner(lint_rc=2, lint_json="")  # 2 no esta en (0, 1)
        code, payload = lg.gate(cfg, str(self.root), runner=runner)
        self.assertEqual(code, 2)
        self.assertIn("sqlfluff falló", payload["error"])

    def test_uses_args_and_files_when_provided(self):
        cfg = _write_cfg(self.root, [{"tool": "sqlfluff", "version": SQLFLUFF_PIN,
                                      "args": ["--dialect", "ansi"]}])
        (self.root / "bad.sql").write_text("select 1\n", encoding="utf-8")
        runner = SqlfluffFakeRunner(lint_json="[]", lint_rc=0)
        lg.gate(cfg, str(self.root), runner=runner)
        lint_calls = [c for c in runner.calls if c[0][:2] == ["sqlfluff", "lint"]]
        self.assertEqual(len(lint_calls), 1)
        # args antes de los archivos, --format json al final
        self.assertEqual(lint_calls[0][0],
                         ["sqlfluff", "lint", "--dialect", "ansi", "bad.sql", "--format", "json"])


@unittest.skipUnless(_HAS_SQLFLUFF, "sqlfluff no disponible (no instalado)")
class IntegrationRealSqlfluff(unittest.TestCase):
    """Integracion REAL con `sqlfluff lint` (runner por defecto = subprocess). Corre solo si
    sqlfluff esta instalado y su version matchea el pin del test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self, **overrides):
        entry = {"tool": "sqlfluff", "version": SQLFLUFF_PIN, "files": "**/*.sql",
                 "args": ["--dialect", "postgres"]}
        entry.update(overrides)
        return _write_cfg(self.root, [entry])

    def test_style_violation_exit1_with_normalized_finding(self):
        (self.root / "bad.sql").write_text("select id,name from users where id=1\n",
                                           encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        findings = payload["results"][0]["findings"]
        self.assertGreaterEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["file"], "bad.sql")
        self.assertEqual(f["line"], 1)
        self.assertTrue(f["code"], "code de regla vacio")  # codigo alfanumerico tipo LT09

    def test_clean_exit0(self):
        (self.root / "ok.sql").write_text(
            "SELECT\n    id,\n    name\nFROM users\nWHERE id = 1\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(), str(self.root))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["findings"], [])

    def test_version_mismatch_real_exit2(self):
        (self.root / "ok.sql").write_text("select 1\n", encoding="utf-8")
        code, payload = lg.gate(self._cfg(version="0.0.0"), str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("entorno inválido", payload["error"])


if __name__ == "__main__":
    unittest.main()