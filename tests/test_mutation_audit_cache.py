"""test_mutation_audit_cache.py — regresión del bug de caché de bytecode en mutation_audit.

BUG: CPython valida un .pyc por (mtime del source, tamaño del source). Dos mutantes
consecutivos del MISMO tamaño de archivo, escritos dentro del mismo segundo, comparten
clave de caché → el segundo mutante cargaba el bytecode STALE del primero y el oráculo lo
reportaba como 'sobreviviente' pese a que los tests SÍ lo mataban (falso sobreviviente).
Repro real: sobre kdd-sample-slugify, la auditoría reportaba 3 sobrevivientes; con
PYTHONDONTWRITEBYTECODE=1 + __pycache__ borrado, solo 1 (el mutante equivalente real).

Por qué testeamos el MECANISMO y no el timing exacto: forzar que dos writes caigan en el
mismo segundo es no determinista entre plataformas/resoluciones de FS/cargas de CI —el bug
es intermitente—, así que un test de timing sería flaky. En su lugar asserteamos los dos
efectos del fix: (1) el subprocess de tests corre con PYTHONDONTWRITEBYTECODE=1 (no se
escribe .pyc nuevo) y (2) el __pycache__ del directorio del target se borra antes de cada
mutante (no queda .pyc stale que cargar). Juntos => bytecode fresco SIEMPRE.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import mutation_audit  # noqa: E402


class BytecodeCacheFixTest(unittest.TestCase):
    def test_purge_removes_existing_pycache(self):
        # __pycache__ pre-existente con un .pyc stale => debe borrarse antes de correr.
        d = Path(tempfile.mkdtemp())
        try:
            target = d / "impl.py"
            target.write_text("def f():\n    return 1\n", encoding="utf-8")
            cache = d / "__pycache__"
            cache.mkdir()
            (cache / "impl.cpython-399.pyc").write_bytes(b"stale bytecode")
            mutation_audit._purge_bytecode_cache(target)
            self.assertFalse(cache.exists(), "el __pycache__ no se borró")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_purge_is_noop_when_no_cache(self):
        # Sin __pycache__ no debe crashear (primer mutante, o directorio limpio).
        d = Path(tempfile.mkdtemp())
        try:
            target = d / "impl.py"
            target.write_text("x = 1\n", encoding="utf-8")
            mutation_audit._purge_bytecode_cache(target)  # no-op, no excepción
            self.assertFalse((d / "__pycache__").exists())
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_mutant_run_purges_cache_and_disables_bytecode_write(self):
        # El mecanismo completo: al correr un mutante se borró el __pycache__ stale y el
        # subprocess recibió PYTHONDONTWRITEBYTECODE=1 en su env.
        d = Path(tempfile.mkdtemp())
        try:
            target = d / "impl.py"
            target.write_text("def f():\n    return 1\n", encoding="utf-8")
            cache = d / "__pycache__"
            cache.mkdir()
            (cache / "impl.cpython-399.pyc").write_bytes(b"stale bytecode")

            captured = {}

            def fake_run(cmd, **kw):
                captured["env"] = kw.get("env")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            with mock.patch.object(mutation_audit.subprocess, "run", fake_run):
                mutation_audit._mutant_survives(
                    ["python", "t.py"], str(d), target,
                    "def f():\n    return 2\n")
            self.assertFalse(cache.exists(),
                             "el __pycache__ del target no se borró antes de correr el mutante")
            self.assertEqual(captured["env"].get("PYTHONDONTWRITEBYTECODE"), "1",
                             "el subprocess de tests no corrió con bytecode deshabilitado")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_dontwritebytecode_propagates_through_full_audit(self):
        # Audit end-to-end con un runner fake: cada invocación a subprocess.run debe llevar
        # PYTHONDONTWRITEBYTECODE=1 (el fix vive en el tool, sin env externo del caller).
        d = Path(tempfile.mkdtemp())
        try:
            target = d / "impl.py"
            target.write_text("def is_adult(age):\n    return age >= 18\n", encoding="utf-8")
            (d / "t.py").write_text("from impl import is_adult\n"
                                    "assert is_adult(18) is True\n"
                                    "assert is_adult(17) is False\n", encoding="utf-8")
            (d / "c.md").write_text(
                '---\ntask: is-adult\ntarget: impl.py\nsignature: "def is_adult(age)"\n'
                'tests: t.py\ntest_command: "python t.py"\ntest_cwd: "."\n---\n',
                encoding="utf-8")
            envs = []

            def fake_run(cmd, **kw):
                envs.append(kw.get("env"))
                return subprocess.CompletedProcess(cmd, 1, "", "")  # todos los mutantes cazados

            with mock.patch.object(mutation_audit.subprocess, "run", fake_run):
                res = mutation_audit.audit(d / "c.md")
            self.assertTrue(envs, "el audit no invocó subprocess.run")
            for env in envs:
                self.assertEqual(env.get("PYTHONDONTWRITEBYTECODE"), "1")
            self.assertTrue(res["ok"], str(res))
            self.assertEqual(res["survived"], [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()