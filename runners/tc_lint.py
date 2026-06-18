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


DEFAULT_LANGUAGE = "python"
# Lenguajes con parser de firma NATIVO (preciso). El resto degrada a aridad genérica.
_NATIVE_SIG = {"python"}


def _parse_sig_python(signature):
    src = str(signature).strip().rstrip(":")  # el contrato no lleva ':' final; lo añadimos
    fn = ast.parse(src + ":\n    pass").body[0]
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("no es un def")
    a = fn.args
    return fn.name, (len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
                     + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


_OPEN, _CLOSE = "([{<", ")]}>"


def _split_top_level(s):
    """Parte `s` por comas de nivel 0, respetando ()[]{}<> y comillas. Determinista, sin deps."""
    out, cur, depth, quote = [], "", 0, None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'`":
            quote = ch
        elif ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def _match_paren(src, open_i):
    """Índice del ')' que cierra el '(' en `open_i`, respetando anidamiento. ValueError si falta."""
    depth = 0
    for i in range(open_i, len(src)):
        depth += 1 if src[i] == "(" else (-1 if src[i] == ")" else 0)
        if depth == 0:
            return i
    raise ValueError("paréntesis de parámetros sin cerrar")


def _parse_sig_generic(signature):
    """Extrae (nombre, aridad) de una firma de un lenguaje con sintaxis de llaves (TS/JS/Go/…)
    sin parser nativo: nombre = identificador antes del grupo de parámetros (quitando genéricos
    `<...>`); aridad = nº de parámetros top-level del primer grupo `(...)` balanceado."""
    src = str(signature).strip()
    open_i = src.find("(")
    if open_i == -1:
        raise ValueError("no se encontró el grupo de parámetros '(...)'")
    close_i = _match_paren(src, open_i)
    prefix = re.sub(r"<[^<>]*>\s*$", "", src[:open_i].strip()).strip()  # quitar genéricos finales
    # nombre = último identificador que no sea una keyword de declaración (const/function/func/…)
    kw = {"const", "let", "var", "function", "async", "export", "default", "public",
          "private", "protected", "static", "func", "fn", "def", "fun", "final", "override"}
    idents = [w for w in re.findall(r"[A-Za-z_$][\w$]*", prefix) if w not in kw]
    if not idents:
        raise ValueError("no se pudo extraer el nombre de la firma")
    inner = src[open_i + 1:close_i].strip()
    n = 0 if not inner else len([p for p in _split_top_level(inner) if p.strip()])
    return idents[-1], n


def parse_sig(signature, language=None):
    """(nombre, aridad) de una firma. python usa el AST (preciso); el resto, aridad genérica."""
    lang = (language or DEFAULT_LANGUAGE).lower()
    if lang in _NATIVE_SIG:
        return _parse_sig_python(signature)
    return _parse_sig_generic(signature)


# ---- una función por regla; cada una devuelve lista de findings ----
def r_required(ctx):
    return [err("tc-required", "falta campo requerido: " + f)
            for f in ["task", "intent", "target", "signature", "budget", "tests"] if f not in ctx["fm"]]

def r_intent_atomic(ctx):
    intent = str(ctx["fm"].get("intent", ""))
    if re.search(r"(?i)\b(y|and|y además|and also)\b", intent):
        return [err("tc-intent-atomic", "intent no es atómico (lleva conector): " + intent)]
    return []

def r_language(ctx):
    lang = ctx["fm"].get("language")
    if lang is None:
        return []  # ausente -> python (back-compat), sin aviso
    if not isinstance(lang, str) or not lang.strip():
        return [err("tc-language", "language debe ser un string no vacío (p.ej. python, typescript)")]
    return []

def r_signature(ctx):
    if "signature" not in ctx["fm"]:
        return []
    lang = (ctx["language"] or DEFAULT_LANGUAGE).lower()
    try:
        ctx["fn_name"], n = parse_sig(ctx["fm"]["signature"], lang)
    except Exception as e:
        verb = "no parsea como def" if lang in _NATIVE_SIG else "no parsea (firma inválida)"
        return [err("tc-signature-valid", f"signature {verb}: {e}")]
    out = []
    if lang not in _NATIVE_SIG:  # degradación documentada: solo aridad, sin parser nativo
        out.append({"level": "warn", "rule": "tc-signature-generic",
                    "msg": f"firma validada por aridad genérica (sin parser nativo para '{lang}')"})
    pmax = ctx["budget"].get("params_max")
    if isinstance(pmax, int) and n > pmax:
        out.append(err("tc-signature-valid", f"la firma tiene {n} params > budget.params_max={pmax}"))
    return out

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


RULES = [r_required, r_language, r_intent_atomic, r_signature, r_budget_sane, r_tests_frozen,
         r_sections, r_stop_rule, r_no_algorithm, r_deps]


def lint(path):
    p = Path(path)
    fm, body = split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return [err("tc-required", "sin front-matter YAML (--- ... ---)")]
    ctx = {"fm": fm, "body": body, "path": p, "budget": fm.get("budget") or {},
           "fn_name": None, "language": fm.get("language")}
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
