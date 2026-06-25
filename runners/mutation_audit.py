#!/usr/bin/env python3
"""mutation_audit.py — fuerza del oráculo vía mutation testing determinista. Sin LLM, zero-dep.

Aplica un set FIJO de mutaciones al target (flip de comparadores y operadores, bool flip, return
None) y, por cada mutante, corre los property-tests congelados del contrato. Si el test PASA contra
un mutante, NO lo cazó: el oráculo es débil ahí (mutante 'sobreviviente'). Mide cuán FUERTE es el
test, no solo que pase. Determinista: operadores fijos, orden de walk del AST, sin azar.

Caro (corre los tests por mutante), así que es una tool OPT-IN, no un stage por defecto del gate.
Uso:  python mutation_audit.py contrato.md      (exit 1 si sobrevive algún mutante)"""
import ast
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402
import task_gate  # noqa: E402

_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
         ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Add: ast.Sub, ast.Sub: ast.Add,
         ast.Mult: ast.Div, ast.Div: ast.Mult, ast.And: ast.Or, ast.Or: ast.And}


def _node_points(n):
    """Puntos de mutación de UN nodo (lista, posible vacía)."""
    if isinstance(n, (ast.BinOp, ast.BoolOp)) and type(n.op) in _SWAP:
        return [("op", n)]
    if isinstance(n, ast.Compare):
        return [("cmp", (n, i)) for i, o in enumerate(n.ops) if type(o) in _SWAP]
    if isinstance(n, ast.Constant) and isinstance(n.value, bool):
        return [("bool", n)]
    # `return <expr>` se muta a `return None`. Excluimos el `return None` LITERAL: mutarlo da código
    # byte-idéntico (no-op) y aparecería como "superviviente" espurio imposible de matar.
    if isinstance(n, ast.Return) and n.value is not None \
            and not (isinstance(n.value, ast.Constant) and n.value.value is None):
        return [("ret", n)]
    return []


def _points(tree):
    """Puntos de mutación en orden de walk del AST. Determinista."""
    pts = []
    for n in ast.walk(tree):
        pts += _node_points(n)
    return pts


def _apply(kind, loc):
    if kind == "op":
        loc.op = _SWAP[type(loc.op)]()
    elif kind == "cmp":
        loc[0].ops[loc[1]] = _SWAP[type(loc[0].ops[loc[1]])]()
    elif kind == "bool":
        loc.value = not loc.value
    elif kind == "ret":
        loc.value = ast.Constant(value=None)


def _kth_mutant(src, k):
    """(código del k-ésimo mutante, descripción). Re-parsea fresco para no arrastrar referencias."""
    tree = ast.parse(src)
    kind, loc = _points(tree)[k]
    _apply(kind, loc)
    line = (loc[0] if kind == "cmp" else loc).lineno
    return ast.unparse(tree), f"{kind}@L{line}"


def _mutant_survives(cmd, cwd, target, mutant):
    """True si el test PASA contra el mutante (no lo cazó). Un timeout (bucle infinito introducido
    por la mutación) NO es sobreviviente: el mutante no hizo pasar el test."""
    target.write_text(mutant, encoding="utf-8", newline="")
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def audit(contract_path):
    """Devuelve {mutants, killed, survived, mutation_score, ok}. Restaura el target byte-exacto."""
    p = Path(contract_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if not fm or not all(k in fm for k in ("target", "tests", "test_command")):
        return {"ok": False, "error": "contrato sin target/tests/test_command", "mutants": 0}
    target, tests = p.parent / fm["target"], p.parent / fm["tests"]
    if not target.exists() or not tests.exists():
        return {"ok": False, "error": "target o tests no existen", "mutants": 0}
    if (fm.get("language") or "python").lower() != "python":
        return {"ok": True, "mutants": 0, "skipped": "no-python"}  # mutaciones solo para Python
    orig = target.read_bytes()
    try:
        src = orig.decode("utf-8")
        n = len(_points(ast.parse(src)))
    except (SyntaxError, UnicodeDecodeError):
        return {"ok": True, "mutants": 0, "skipped": "no-parsea"}  # target no parsea: nada que mutar
    cmd, cwd = shlex.split(fm["test_command"]), task_gate._resolve_test_cwd(fm, target, p.parent)
    survived = []
    try:
        for k in range(n):
            mutant, desc = _kth_mutant(src, k)
            if _mutant_survives(cmd, cwd, target, mutant):
                survived.append(desc)
    finally:
        target.write_bytes(orig)  # restauración byte-exacta (line endings intactos)
    killed = n - len(survived)
    return {"mutants": n, "killed": killed, "survived": survived,
            "mutation_score": round(killed / n, 3) if n else 1.0, "ok": not survived}


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print("uso: python mutation_audit.py contrato.md", file=sys.stderr)
        return 2
    res = audit(sys.argv[1])
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
