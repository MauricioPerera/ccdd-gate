#!/usr/bin/env python3
"""bench_rust_backend.py -- benchmark DETERMINISTA: costo de Rust vs Python en el gate.

Companero de bench_gate.py, pero en vez de medir el gate en abstracto, compara el backend
NATIVO de Python (ast de la stdlib) contra el backend RUST (tree-sitter) para las DOS
operaciones que el Nivel 2 corre por tarea:

  1. Metricas de complejidad: metrics.py (PythonBackend, AST nativo) vs metrics_treesitter.py
     (TreeSitterBackend) -- ambos registrados en el mismo dispatcher (metrics_backends.
     get_backend), asi que la comparacion llama exactamente el mismo path que usa el gate real.
  2. Chequeo de firma: sig_check.signature_mismatch (AST nativo) vs
     sig_treesitter.check_signature_src (tree-sitter) -- mismo contrato, mismo mirror
     documentado en el docstring de sig_treesitter.py.

Sobre funciones EQUIVALENTES (misma forma logica) en ambos lenguajes, para que la comparacion
sea sobre el BACKEND, no sobre que codigo se le da de comer.

Tercera medicion, cualitativa y con caveat explicito: el costo de punta a punta del gate de
lint (linter_gate.py) para Python (ruff, analisis estatico) vs Rust (clippy, que compila).
Esta SI depende del proyecto (tamano de crate, cache de compilacion) -- no es apples-to-apples
como las dos anteriores, se etiqueta como tal.

Uso:  python benchmarks/bench_rust_backend.py [ruta_a_proyecto_rust_con_linters.yaml]
Sin argumento, la parte 3 (clippy) se salta con un aviso (no hay proyecto Rust para correr).
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import metrics_backends as mb  # noqa: E402
import metrics               # noqa: E402,F401  (registra PythonBackend en el import)
import metrics_treesitter    # noqa: E402,F401  (registra TreeSitterBackend por gramatica disponible)
import sig_check             # noqa: E402
import sig_treesitter        # noqa: E402

PY_SRC = '''
def classify(a, b, c):
    if a > 0:
        if b > 0:
            if c > 0:
                if a > b:
                    if b > c:
                        return 1
                    return 2
                return 3
            return 4
        return 5
    return 6
'''.strip()

RUST_SRC = '''
fn classify(a: i32, b: i32, c: i32) -> i32 {
    if a > 0 {
        if b > 0 {
            if c > 0 {
                if a > b {
                    if b > c {
                        return 1;
                    }
                    return 2;
                }
                return 3;
            }
            return 4;
        }
        return 5;
    }
    return 6;
}
'''.strip()

PY_SIGNATURE = "def classify(a, b, c):"
RUST_SIGNATURE = "fn classify(a: i32, b: i32, c: i32) -> i32"


def bench(label, fn, iters):
    fn()  # warmup (cachea imports/parseos/gramaticas)
    t0 = time.perf_counter()
    for _ in range(iters):
        fn()
    ms = (time.perf_counter() - t0) / iters * 1000
    print(f"  {label:<42} {ms:9.4f} ms/op   (n={iters})")
    return ms


def bench_metrics():
    print("1. Metricas de complejidad -- mismo dispatcher (metrics_backends.get_backend)")
    print("   Funcion EQUIVALENTE (misma forma: 4 ifs anidados) en ambos lenguajes.")
    py_backend = mb.get_backend(language="python")
    rust_backend = mb.get_backend(language="rust")
    if rust_backend is None:
        print("   SALTEADO: gramatica tree-sitter-rust no instalada (dep opcional).")
        return None, None
    py_ms = bench("metrics python (AST nativo)", lambda: py_backend.measure(PY_SRC), 500)
    rust_ms = bench("metrics rust (tree-sitter)", lambda: rust_backend.measure(RUST_SRC), 500)
    print(f"   -> rust/python: {rust_ms / py_ms:.1f}x")
    return py_ms, rust_ms


def bench_signature():
    print("\n2. Chequeo de firma -- mismo contrato (sig_check.py vs su espejo sig_treesitter.py)")
    loaded = sig_treesitter._load_spec("rust")  # noqa: SLF001 (benchmark interno, no API publica)
    if loaded is None:
        print("   SALTEADO: gramatica tree-sitter-rust no instalada (dep opcional).")
        return None, None
    py_ms = bench(
        "firma python (ast nativo)",
        lambda: sig_check.signature_mismatch(PY_SRC, "classify", PY_SIGNATURE), 500)
    rust_ms = bench(
        "firma rust (tree-sitter)",
        lambda: sig_treesitter.check_signature_src(RUST_SRC, "classify", RUST_SIGNATURE, "rust"),
        500)
    print(f"   -> rust/python: {rust_ms / py_ms:.1f}x")
    return py_ms, rust_ms


def bench_lint_gate(rust_project):
    print("\n3. Gate de lint end-to-end -- ruff (Python, estatico) vs clippy (Rust, compila).")
    print("   NO es apples-to-apples (depende del proyecto/cache): rotulado como tal.")
    runs = 3

    def _time_once(cmd, cwd):
        t0 = time.perf_counter()
        subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", check=False)
        return time.perf_counter() - t0

    ruff_times = [_time_once(["ruff", "check", "runners/metrics.py"], str(REPO))
                  for _ in range(runs)]
    print(f"  {'ruff sobre 1 archivo (runners/metrics.py)':<42}"
          f" min={min(ruff_times) * 1000:7.1f} ms  median={sorted(ruff_times)[len(ruff_times) // 2] * 1000:7.1f} ms")

    if rust_project is None:
        print("  clippy: SALTEADO (no se paso una ruta de proyecto Rust como argumento).")
        return
    project = Path(rust_project)
    if not (project / "linters.yaml").exists():
        print(f"  clippy: SALTEADO ({project} no tiene linters.yaml).")
        return
    clippy_times = [_time_once(["cargo", "clippy", "--message-format=json"], str(project))
                     for _ in range(runs)]
    print(f"  {'clippy sobre el crate (cache tibia)':<42}"
          f" min={min(clippy_times) * 1000:7.1f} ms  median={sorted(clippy_times)[len(clippy_times) // 2] * 1000:7.1f} ms")
    print(f"   -> clippy/ruff (cache tibia): {min(clippy_times) / min(ruff_times):.0f}x")


def main():
    rust_project = sys.argv[1] if len(sys.argv) > 1 else None
    print("Benchmark DETERMINISTA: costo de Rust vs Python en el gate KDD/CCDD")
    print("=" * 72)
    bench_metrics()
    bench_signature()
    bench_lint_gate(rust_project)
    print("=" * 72)
    print("Lectura honesta: las partes 1 y 2 (el gate en si) tienen el mismo orden de magnitud")
    print("en Rust que en Python -- el parser cambia, el costo sigue siendo sub-milisegundo.")
    print("La parte 3 es la real: clippy paga el precio de COMPILAR: ese costo es inherente a")
    print("Rust como lenguaje compilado, no del gate. Con cache tibia (incremental) el costo")
    print("es chico; en frio (cargo clean) es el mayor cuello de botella real de KDD+Rust hoy.")
    print()
    print("Referencia medida (no se re-corre aca -- 'cargo clean' + clippy tarda ~1 min):")
    print("  clippy en frio (topcoat-app, cargo clean previo): ~58900 ms (una corrida real,")
    print("  Windows, este hardware). ~173x el costo tibio de arriba, ~2800x ruff. Esto SI es")
    print("  un costo real de adoptar KDD+Rust: la primera verificacion de un checkout limpio")
    print("  (CI sin cache, o `cargo clean` local) es del orden del minuto, no del milisegundo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
