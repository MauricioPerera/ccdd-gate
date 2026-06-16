#!/usr/bin/env python3
"""bench_gate.py — benchmark DETERMINISTA del gate. Sin LLM, reproducible en cualquier máquina.

Mide el wall-time del veredicto (métricas AST + tc_lint + task_gate completo) sobre los
contratos de ejemplo. El punto: la verificación que reemplaza a una llamada-LLM-de-review
cuesta milisegundos y CERO tokens, idéntica corrida a corrida.

Uso:  python benchmarks/bench_gate.py
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))
import metrics    # noqa: E402
import tc_lint    # noqa: E402
import task_gate  # noqa: E402


def bench(label, fn, iters):
    fn()  # warmup (cachea imports/parseos)
    t0 = time.perf_counter()
    for _ in range(iters):
        fn()
    ms = (time.perf_counter() - t0) / iters * 1000
    print(f"  {label:<34} {ms:9.3f} ms/op   (n={iters})")
    return ms


def main():
    sandbox = REPO / "examples" / "sandbox"
    task = str(sandbox / "task.md")
    src = (sandbox / "disassembler.py").read_text(encoding="utf-8")

    print("Benchmark DETERMINISTA del gate — 0 tokens LLM, reproducible byte-a-byte")
    print("-" * 64)
    bench("metrics.functions_metrics (AST)", lambda: metrics.functions_metrics(src), 500)
    bench("tc_lint.lint (valida task-contract)", lambda: tc_lint.lint(task), 500)
    bench("task_gate.gate (verdicto pleno)", lambda: task_gate.gate(task), 30)
    print("-" * 64)
    print("Referencia: una 'review' por LLM = ~1-2k tokens in + segundos de latencia + costo API.")
    print("El gate: 0 tokens, sin red, mismo veredicto siempre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
