#!/usr/bin/env python3
"""tc_lint.py — linter del TASK-CONTRACT (ver TASK_CONTRACT.md). Valida que el contrato que el
modelo grande emite esté bien formado ANTES de pasarlo al pequeño: anti-desvarío del autor.

Uso:  python tc_lint.py task.md
Salida: JSON {findings:[{level,rule,msg}], ok}. Exit 0 si no hay errores, 1 si los hay.
Zero-dep salvo pyyaml (ya requerido por CCDD). Cada regla es una función pequeña (baja complejidad)."""
import ast
import json
import re
import sys
from pathlib import Path

import yaml

GLOBAL_MAX = {"cyclomatic_max": 20, "nesting_max": 4, "lines_max": 80, "params_max": 5}
SECTIONS = ["## Intent", "## Interface", "## Invariants", "## Examples",
            "## Do / Don't", "## Tests", "## Constraints"]


def split_front_matter(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    return (yaml.safe_load(m.group(1)) or {}, m.group(2)) if m else (None, text)


def section_body(body, header):
    i = body.find(header)
    if i == -1:
        return ""
    nxt = body.find("\n## ", i + len(header))
    return body[i + len(header): nxt if nxt != -1 else len(body)]


def parse_sig(signature):
    src = str(signature).strip().rstrip(":")  # el contrato no lleva ':' final; lo añadimos
    fn = ast.parse(src + ":\n    pass").body[0]
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("no es un def")
    a = fn.args
    return fn.name, (len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
                     + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


# ---- una función por regla; cada una devuelve lista de findings ----
def r_required(ctx):
    return [err("tc-required", "falta campo requerido: " + f)
            for f in ["task", "intent", "target", "signature", "budget", "tests"] if f not in ctx["fm"]]

def r_intent_atomic(ctx):
    intent = str(ctx["fm"].get("intent", ""))
    if re.search(r"(?i)\b(y|and|y además|and also)\b", intent):
        return [err("tc-intent-atomic", "intent no es atómico (lleva conector): " + intent)]
    return []

def r_signature(ctx):
    if "signature" not in ctx["fm"]:
        return []
    try:
        ctx["fn_name"], n = parse_sig(ctx["fm"]["signature"])
    except Exception as e:
        return [err("tc-signature-valid", "signature no parsea como def: " + str(e))]
    pmax = ctx["budget"].get("params_max")
    if isinstance(pmax, int) and n > pmax:
        return [err("tc-signature-valid", f"la firma tiene {n} params > budget.params_max={pmax}")]
    return []

def r_budget_sane(ctx):
    b = ctx["budget"]
    if not isinstance(b, dict):
        return [err("tc-budget-sane", "budget debe ser un mapa")]
    out = []
    for k, cap in GLOBAL_MAX.items():
        v = b.get(k)
        if isinstance(v, int) and v > cap:
            out.append({"level": "warn" if k == "params_max" else "error", "rule": "tc-budget-sane",
                        "msg": f"budget.{k}={v} excede el tope global firmado ({cap})"})
    return out

def r_tests_frozen(ctx):
    tests = ctx["fm"].get("tests")
    if not tests:
        return []
    tp = ctx["path"].parent / tests
    if not tp.exists() or tp.stat().st_size == 0:
        return [err("tc-tests-frozen", "los property-tests deben existir y no estar vacíos: " + str(tests))]
    if ctx["fn_name"] and ctx["fn_name"] not in tp.read_text(encoding="utf-8"):
        return [err("tc-tests-frozen", f"los tests no referencian la firma '{ctx['fn_name']}'")]
    return []

def r_sections(ctx):
    body = ctx["body"]
    pos = [(s, body.find(s)) for s in SECTIONS]
    out = [err("tc-sections", "falta la sección obligatoria: " + s) for s, i in pos if i == -1]
    present = [i for _, i in pos if i != -1]
    if present != sorted(present):
        out.append(err("tc-sections", "las secciones no están en el orden canónico"))
    ex = section_body(body, "## Examples")
    n = len([ln for ln in ex.splitlines() if ln.strip().startswith("- ") or "→" in ln or "->" in ln])
    if ex and n < 2:
        out.append(err("tc-sections", "## Examples debe tener ≥2 ejemplos resueltos"))
    return out

def r_stop_rule(ctx):
    cons = section_body(ctx["body"], "## Constraints").upper().replace("Á", "A")
    return [] if "PARAR" in cons else [err("tc-stop-rule", "## Constraints debe incluir 'PARAR y reportar si...'")]

def r_no_algorithm(ctx):
    head = section_body(ctx["body"], "## Intent") + section_body(ctx["body"], "## Interface")
    if re.search(r"(?im)^\s*1\.\s+.*\n\s*2\.\s+", head) or re.search(r"(?i)\b(primero|luego|después)\b,", head):
        return [{"level": "warn", "rule": "tc-no-algorithm",
                 "msg": "parece describir el algoritmo paso a paso (define el QUÉ, no el CÓMO)"}]
    return []

def r_deps(ctx):
    out = []
    if "deps_allowed" not in ctx["fm"]:
        out.append({"level": "warn", "rule": "tc-deps-declared", "msg": "declara deps_allowed (aunque sea [])"})
    if not ctx["fm"].get("forbids"):
        out.append({"level": "warn", "rule": "tc-deps-declared", "msg": "recomendado: forbids no vacío"})
    return out


def err(rule, msg):
    return {"level": "error", "rule": rule, "msg": msg}


RULES = [r_required, r_intent_atomic, r_signature, r_budget_sane, r_tests_frozen,
         r_sections, r_stop_rule, r_no_algorithm, r_deps]


def lint(path):
    p = Path(path)
    fm, body = split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return [err("tc-required", "sin front-matter YAML (--- ... ---)")]
    ctx = {"fm": fm, "body": body, "path": p, "budget": fm.get("budget") or {}, "fn_name": None}
    findings = []
    for rule in RULES:
        findings += rule(ctx)
    return findings


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print("uso: python tc_lint.py task.md", file=sys.stderr)
        return 2
    findings = lint(sys.argv[1])
    errors = sum(1 for f in findings if f["level"] == "error")
    print(json.dumps({"file": sys.argv[1], "ok": errors == 0, "errors": errors,
                      "warnings": len(findings) - errors, "findings": findings},
                     ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
