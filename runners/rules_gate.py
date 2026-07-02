#!/usr/bin/env python3
"""rules_gate.py — aplica los checks DETERMINISTAS de ccdd-gate PROJECT-WIDE por glob.

Idea declarativa tomada de autorules (reglas = archivo + glob), pero con árbitro INSOBORNABLE: el
check es AST determinista, NO un LLM. Cierra un hueco real: los gates de antipatrón (purity,
bare-except, mutable-defaults, assert, none-eq) hoy solo se disparan por contrato; esto los vuelve
política de repo aplicable a TODOS los archivos de un glob.

Config (YAML): lista de reglas, cada una { check: <nombre>, files: <glob> }.
Uso:  python rules_gate.py [rules.yaml] [root]
Exit: 0 sin violaciones · 1 violaciones · 2 config inválida. Sin LLM."""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bareexcept_check  # noqa: E402
import mutdef_check      # noqa: E402
import nonecmp_check     # noqa: E402
import assert_check      # noqa: E402
import purity_check      # noqa: E402

# nombre de regla -> callable(source, fn_name, target_line) de un check determinista existente.
CHECKS = {
    "bare_except": bareexcept_check.bare_except_lines,
    "assert": assert_check.assert_lines,
    "none_eq": nonecmp_check.none_eq_lines,
    "mutable_defaults": mutdef_check.mutable_defaults,
    "purity": purity_check.impure_operations,
}


def _all_functions(tree):
    """(nombre, lineno) de cada def/async def del árbol."""
    return [(n.name, n.lineno) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def scan_source(source: str, check: str) -> list:
    """Líneas (ordenadas, sin duplicados) que el `check` flaggea en TODAS las funciones de `source`.
    Para checks por-línea (bare_except/assert/none_eq) usa las líneas; para los por-función
    (mutable_defaults/purity) usa la línea del `def`. [] si check desconocido o source no parsea."""
    fn = CHECKS.get(check)
    if fn is None:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = set()
    for name, lineno in _all_functions(tree):
        res = fn(source, name, lineno)
        if not res:
            continue
        if all(isinstance(x, int) for x in res):
            lines.update(res)
        else:
            lines.add(lineno)
    return sorted(lines)


def _load_rules(rules_path):
    """Lista de reglas {check, files} validadas, o (None, error). YAML mal formado o
    archivo ausente → (None, msg) → INVALID (exit 2), SIN traceback (contrato doc)."""
    import yaml
    p = Path(rules_path)
    if not p.exists():
        return None, f"rules.yaml no encontrado: {rules_path}"
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return None, f"rules.yaml mal formado: {e}"
    if not isinstance(data, list):
        return None, "rules debe ser una lista de {check, files}"
    for r in data:
        if not isinstance(r, dict) or "check" not in r or "files" not in r:
            return None, f"regla inválida (faltan check/files): {r}"
        if r["check"] not in CHECKS:
            return None, f"check desconocido '{r['check']}'; válidos: {sorted(CHECKS)}"
    return data, None


def gate(rules_path: str, root: str = ".") -> dict:
    rules, err = _load_rules(rules_path)
    if err:
        return {"verdict": "INVALID", "detail": err}
    rootp = Path(root)
    violations = []
    for rule in rules:
        for f in sorted(rootp.glob(rule["files"])):
            if not f.is_file():
                continue
            flagged = scan_source(f.read_text(encoding="utf-8"), rule["check"])
            if flagged:
                violations.append({"file": str(f.relative_to(rootp)), "check": rule["check"], "lines": flagged})
    return {"verdict": "FAIL" if violations else "PASS", "violations": violations}


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    rules_path = sys.argv[1] if len(sys.argv) > 1 else "rules.yaml"
    root = sys.argv[2] if len(sys.argv) > 2 else "."
    v = gate(rules_path, root)
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["verdict"] == "PASS" else (2 if v["verdict"] == "INVALID" else 1)


if __name__ == "__main__":
    sys.exit(main())
