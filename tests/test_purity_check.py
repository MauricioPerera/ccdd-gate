"""test_purity_check.py — property-tests CONGELADOS de impure_operations (runners/purity_check.py).
Oráculo independiente: casos fijos. impure_operations devuelve la lista ORDENADA y SIN duplicados de
las "marcas" de impureza halladas en el cuerpo de la función. Vacío = función pura. Sin LLM."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runners"))
from purity_check import impure_operations  # noqa: E402


class TestImpureOperations(unittest.TestCase):
    def test_pure(self):
        self.assertEqual(impure_operations("def f(x):\n    return x + 1\n", "f"), [])

    def test_print(self):
        self.assertEqual(impure_operations("def f(x):\n    print(x)\n    return x\n", "f"), ["print"])

    def test_open(self):
        self.assertEqual(impure_operations("def f(x):\n    open('a')\n    return x\n", "f"), ["open"])

    def test_global(self):
        self.assertEqual(impure_operations("def f(x):\n    global G\n    return x\n", "f"), ["global"])

    def test_import_inside(self):
        self.assertEqual(impure_operations("def f(x):\n    import os\n    return os\n", "f"), ["import"])

    def test_eval_exec(self):
        self.assertEqual(impure_operations("def f(x):\n    return eval(x)\n", "f"), ["eval"])

    def test_multiple_sorted_unique(self):
        src = "def f(x):\n    print(x)\n    open('a')\n    print(x)\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["open", "print"])

    def test_nonlocal(self):
        src = "def outer():\n    y = 1\n    def f(x):\n        nonlocal y\n        return x\n    return f\n"
        self.assertEqual(impure_operations(src, "f"), ["nonlocal"])

    def test_non_denylist_call_is_pure(self):
        # len() es una llamada pero NO está en el denylist -> pura. Mata el mutante and->or de L33.
        self.assertEqual(impure_operations("def f(x):\n    return len(x)\n", "f"), [])

    def test_not_found(self):
        self.assertEqual(impure_operations("def g(x):\n    print(x)\n", "f"), [])

    def test_parse_error(self):
        self.assertEqual(impure_operations("def (bad", "f"), [])

    def test_target_line_disambiguates(self):
        src = "def f(a):\n    print(a)\n\ndef f(x):\n    return x\n"  # f@L1 impuro, f@L4 puro
        self.assertEqual(impure_operations(src, "f", target_line=4), [])
        self.assertEqual(impure_operations(src, "f", target_line=1), ["print"])

    # --- calls por atributo peligrosos (falso negativo: _DENYLIST sólo tenía nombres planos) ---
    def test_os_system(self):
        self.assertEqual(impure_operations("def f(x):\n    os.system('echo hi')\n    return x\n", "f"), ["system"])

    def test_os_popen(self):
        self.assertEqual(impure_operations("def f(x):\n    os.popen('ls')\n    return x\n", "f"), ["popen"])

    def test_subprocess_run(self):
        src = "def f(x):\n    subprocess.run(['ls'])\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["run"])

    def test_subprocess_check_output(self):
        src = "def f(x):\n    subprocess.check_output(['ls'])\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["check_output"])

    def test_sys_stdout_write(self):
        src = "def f(x):\n    sys.stdout.write('hi')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["write"])

    def test_pathlib_write_text(self):
        src = "def f(x):\n    p.write_text('hi')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["write_text"])

    def test_requests_get(self):
        src = "def f(x):\n    requests.get('http://x')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["get"])

    def test_urllib_urlopen(self):
        src = "def f(x):\n    urllib.request.urlopen('http://x')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["urlopen"])

    def test_shutil_any_method(self):
        src = "def f(x):\n    shutil.copy('a', 'b')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["copy"])

    def test_socket_any_method(self):
        src = "def f(x):\n    socket.socket()\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), ["socket"])

    # --- evita falsos positivos obvios ---
    def test_dict_get_not_flagged(self):
        # .get de un dict (receptor no 'requests') es común y NO es I/O.
        self.assertEqual(impure_operations("def f(x):\n    return x.get('a')\n", "f"), [])

    def test_obj_call_not_flagged(self):
        # .call de un objeto cualquiera (receptor no 'subprocess') no se marca.
        self.assertEqual(impure_operations("def f(x):\n    x.call()\n    return x\n", "f"), [])

    # --- falso positivo por función anidada: NO se atribuye al target exterior ---
    def test_nested_print_not_attributed(self):
        src = "def f(x):\n    def inner():\n        print('x')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), [])

    def test_nested_os_system_not_attributed(self):
        src = "def f(x):\n    def inner():\n        os.system('rm')\n    return x\n"
        self.assertEqual(impure_operations(src, "f"), [])


if __name__ == "__main__":
    unittest.main()
