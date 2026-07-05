#!/usr/bin/env python3
"""repo_gate.py — dogfooding del complexity gate sobre el PROPIO repo (sin LLM).

Recorre el código de PRODUCCIÓN (toda extensión con backend registrado, salvo fixtures/,
tests/ y artefactos) y aplica el mismo veredicto determinista que `complexity_gate.py`:
FALLA (exit 1) si alguna función supera el umbral CRÍTICA de los thresholds firmados. Los
avisos ALTA se reportan pero NO bloquean (espejo de la semántica del gate: "Revisar, no
bloquea").

MULTI-LENGUAJE: cubre todo lenguaje con backend registrado (Python siempre; JS/TS/JSX/TSX
si tree-sitter está instalado). Las extensiones sin backend se ignoran (no-op).

Uso:  python runners/repo_gate.py [raíz]   (raíz por defecto: el directorio del repo)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402,F401  (registra el backend python al importarse)
try:
    import metrics_treesitter  # noqa: E402,F401  (registra JS/TS/JSX/TSX si tree-sitter está)
except Exception:
    pass
import metrics_backends as mb  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Directorios excluidos del gate del repo: fixtures (complejos a propósito, son los casos de
# prueba del medidor), tests (no es código de producción) y artefactos de build/deps.
_EXCLUDE_DIRS = ("fixtures", "tests", "__pycache__", ".git", ".venv", "venv",
                 "node_modules", "dist", "build")


def _is_production(rel: Path) -> bool:
    return not any(part in _EXCLUDE_DIRS for part in rel.parts)


def _scan_file(path: Path):
    """(crit, high) findings de un archivo, o (None, None) si no hay backend."""
    try:
        backend = mb.get_backend(filename=path.name)
    except KeyError:
        return None, None
    det = backend.extract_source(path.read_text(encoding="utf-8"), path.name)
    findings = det.get("findings", [])
    crit = [f for f in findings if f.get("severity") == "CRÍTICA"]
    high = [f for f in findings if f.get("severity") == "ALTA"]
    return crit, high


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    exts = set(mb.supported_extensions())  # todo lenguaje con backend registrado
    failed, high_total, scanned = [], 0, 0
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in exts or not path.is_file():
            continue
        rel = path.relative_to(root)
        if not _is_production(rel):
            continue
        crit, high = _scan_file(path)
        if crit is None:
            continue
        scanned += 1
        high_total += len(high)
        for f in crit:
            failed.append(f"  • {rel}::{f['function']}: {f['metric']} = {f['value']} (CRÍTICA)")
    if failed:
        print(f"[repo-gate] FAIL — {len(failed)} función(es) CRÍTICA en código de producción "
              f"(umbrales firmados). Refactoriza o registra una excepción firmada:", file=sys.stderr)
        print("\n".join(failed), file=sys.stderr)
        return 1
    print(f"[repo-gate] PASS — {scanned} archivo(s) de producción bajo umbral CRÍTICA "
          f"({high_total} aviso(s) ALTA, no bloquean).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
