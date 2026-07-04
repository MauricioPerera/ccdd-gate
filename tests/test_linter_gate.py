"""test_linter_gate.py — tests de linter_gate (linters externos deterministas como checks opt-in).

Sin LLM. (a) Unit sobre normalizacion y politicas inyectando un runner fake (version mismatch,
ausente+required, ausente+no-required, findings, limpio, config invalida, glob vacio).
(b) Integracion REAL con ruff: tempdir con F401 -> exit 1; arreglado -> exit 0; mismatch -> exit 2.
Los de integracion saltan limpios (skipUnless) si ruff no esta o su version != pin del test."""
import shutil
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
        cfg = _write_cfg(self.root, [{"tool": "clippy", "version": "1.0"}])
        code, payload = lg.gate(cfg, str(self.root), runner=FakeRunner())
        self.assertEqual(code, 2)
        self.assertIn("clippy", payload["error"])

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


if __name__ == "__main__":
    unittest.main()