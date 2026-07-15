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
try:
    _tpath = Path(__file__).parent.parent / "contracts" / "task-author-agent" / "thresholds.txt"
    if _tpath.exists():
        for _k in GLOBAL_MAX.keys():
            _m = re.search(rf"{_k}\s*≤\s*(\d+)", _tpath.read_text(encoding="utf-8"))
            if _m:
                GLOBAL_MAX[_k] = int(_m.group(1))
except Exception:
    pass
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


def _scan_delim(ch, depth, quote):
    """Actualiza (depth, quote) para un carácter fuera de string (guard clauses, sin anidar)."""
    if ch in "\"'`":
        return depth, ch
    if ch in _OPEN:
        return depth + 1, quote
    if ch in _CLOSE:
        return max(0, depth - 1), quote
    return depth, quote


def _split_top_level(s):
    """Parte `s` por comas de nivel 0, respetando ()[]{}<> y comillas. Determinista, sin deps."""
    out, cur, depth, quote = [], "", 0, None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        depth, quote = _scan_delim(ch, depth, quote)
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
            for f in ["task", "intent", "target", "signature", "budget", "tests", "test_command"] if f not in ctx["fm"]]

def r_test_command(ctx):
    cmd = ctx["fm"].get("test_command")
    if not isinstance(cmd, str) or not cmd.strip():
        return [err("tc-test-command", "test_command debe ser un string no vacío con el comando de ejecución (ej. 'npm test')")]
    return []

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
    pmax = ctx["budget"].get("params_max") if isinstance(ctx["budget"], dict) else None
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

def _find_repo_root(start):
    """Sube desde `start` buscando el ancestro mas cercano con `.git`. None si no lo encuentra."""
    cur = Path(start).resolve()
    for parent in (cur, *cur.parents):
        if (parent / ".git").exists():
            return parent
    return None


def resolve_contract_path(contract_dir, rel):
    """Resuelve `rel` (target/tests del frontmatter) relativo a `contract_dir` -- comportamiento
    historico, intacto: si esa ruta existe, es la que se usa SIEMPRE, sin excepcion.

    Si no existe ahi, cae a resolverla relativa a la raiz del repo (el ancestro mas cercano con
    `.git` subiendo desde `contract_dir`). Soporta contratos que declaran `target`/`tests`
    relativos a la raiz del proyecto (convencion de KDD-template's validate_contracts.py) en vez
    de relativos al propio contrato con `../..` (convencion nativa de este gate). Retrocompatible
    por diseno: nunca cambia una resolucion que ya funcionaba."""
    p = Path(contract_dir) / rel
    if p.exists():
        return p
    root = _find_repo_root(contract_dir)
    if root is not None:
        alt = root / rel
        if alt.exists():
            return alt
    return p


def r_tests_frozen(ctx):
    tests = ctx["fm"].get("tests")
    if not tests:
        return []
    tp = resolve_contract_path(ctx["path"].parent, tests)
    if not tp.exists() or tp.stat().st_size == 0:
        return [err("tc-tests-frozen", "los property-tests deben existir y no estar vacíos: " + str(tests))]
    if ctx["fn_name"] and ctx["fn_name"] not in tp.read_text(encoding="utf-8"):
        return [err("tc-tests-frozen", f"los tests no referencian la firma '{ctx['fn_name']}'")]
    return []


def _is_assert_call(call):
    f = call.func
    name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
    return name.startswith("assert") or name in ("fail", "raises")


def r_tests_assert(ctx):
    """El test congelado (Python) DEBE tener al menos una aserción: un oráculo sin assert hace que
    el gate pase sin verificar nada (test vacuo). Zero-dep, determinista. Solo Python; otros
    lenguajes se omiten (sus aserciones tienen otra forma)."""
    lang = ctx["language"] if isinstance(ctx["language"], str) else DEFAULT_LANGUAGE
    if lang.lower() != "python":
        return []
    tests = ctx["fm"].get("tests")
    if not tests:
        return []
    tp = resolve_contract_path(ctx["path"].parent, tests)
    if not tp.exists():
        return []  # la ausencia ya la reporta r_tests_frozen
    try:
        tree = ast.parse(tp.read_text(encoding="utf-8"))
    except Exception:
        return []  # sintaxis no analizable como Python
    has = any(isinstance(n, ast.Assert) or (isinstance(n, ast.Call) and _is_assert_call(n))
              for n in ast.walk(tree))
    if not has:
        return [err("tc-tests-assert", "el test congelado no tiene ninguna aserción (oráculo vacío): "
                    "un test sin assert hace que el gate pase sin verificar nada")]
    return []

def _count_examples(body):
    """(texto de ## Examples, nº de líneas-ejemplo)."""
    ex = section_body(body, "## Examples")
    lines = [ln for ln in ex.splitlines()
             if ln.strip().startswith("- ") or "→" in ln or "->" in ln]
    return ex, len(lines)


def r_sections(ctx):
    body = ctx["body"]
    pos = [(s, body.find(s)) for s in SECTIONS]
    out = [err("tc-sections", "falta la sección obligatoria: " + s) for s, i in pos if i == -1]
    present = [i for _, i in pos if i != -1]
    if present != sorted(present):
        out.append(err("tc-sections", "las secciones no están en el orden canónico"))
    ex, n = _count_examples(body)
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

# formatos válidos de `issue`: owner/repo#N  |  URL de issue/pull de github.com
_ISSUE_SHORT = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")
_ISSUE_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/(issues|pull)/\d+$")


def valid_issue_ref(s):
    """True si `s` es una referencia de issue válida (owner/repo#N o URL de github.com)."""
    s = str(s).strip()
    return bool(_ISSUE_SHORT.match(s) or _ISSUE_URL.match(s))


def r_issue_ref(ctx):
    """Vínculo contrato->issue (opt-in, back-compat): sin `issue` no rompe nada. Con `issue`,
    valida el formato (error si inválido). Con `require_issue: true`, avisa si falta."""
    fm = ctx["fm"]
    issue = fm.get("issue")
    if issue is None:
        if fm.get("require_issue"):
            return [{"level": "warn", "rule": "tc-issue-ref",
                     "msg": "require_issue=true pero falta el campo 'issue' (owner/repo#N o URL)"}]
        return []
    if not valid_issue_ref(issue):
        return [err("tc-issue-ref", f"formato de 'issue' inválido: {issue} "
                    "(usa owner/repo#N o https://github.com/owner/repo/issues/N)")]
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


def r_target_atomic(ctx):
    target = ctx["fm"].get("target")
    if not target:
        return []
    if isinstance(target, list) or (isinstance(target, str) and ("," in target or "\n" in target)):
        return [err("tc-target-atomic", "El campo 'target' debe ser UN SOLO archivo. Para refactors que crucen archivos, crea múltiples Task Contracts.")]
    return []


# Schema formal del front-matter (fuente única de la FORMA). La validación semántica (intent
# atómico, budget ≤ topes, firma parseable, tests congelados) la siguen haciendo las reglas de abajo.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "task_contract.schema.json"
_schema_cache = None


def _load_task_schema():
    global _schema_cache
    if _schema_cache is None and _SCHEMA_PATH.exists():
        _schema_cache = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema_cache


def r_schema(ctx):
    """Capa 1: valida la FORMA del front-matter contra task_contract.schema.json. Degrada a no-op
    si falta el schema o jsonschema (tc_lint sigue usable solo con pyyaml)."""
    schema = _load_task_schema()
    if not schema:
        return []
    try:
        import jsonschema
    except ImportError:
        return []
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for e in sorted(validator.iter_errors(ctx["fm"]), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in e.path) or "(raíz)"
        out.append(err("tc-schema", f"forma inválida en '{loc}': {e.message}"))
    return out


RULES = [r_schema, r_required, r_test_command, r_language, r_intent_atomic, r_target_atomic, r_signature, r_budget_sane, r_tests_frozen,
         r_tests_assert, r_sections, r_stop_rule, r_no_algorithm, r_deps, r_issue_ref]


# ---- reglas de un contrato de GRUPO (kind: group): compone funciones u otros grupos ----
def r_group_required(ctx):
    return [err("tc-group-required", "falta campo requerido en grupo: " + f)
            for f in ["task", "intent", "children", "integration_test_command"] if f not in ctx["fm"]]

def r_group_children(ctx):
    ch = ctx["fm"].get("children")
    if ch is None:
        return []  # ausencia ya la cubre r_group_required
    if not isinstance(ch, list) or not ch:
        return [err("tc-group-children", "children debe ser una lista NO vacía de rutas a contratos .md")]
    if any(not isinstance(c, str) or not c.strip() for c in ch):
        return [err("tc-group-children", "cada child debe ser una ruta (string) a un contrato .md")]
    return []

def r_integration_command(ctx):
    cmd = ctx["fm"].get("integration_test_command")
    if cmd is None:
        return []  # ausencia ya la cubre r_group_required
    if not isinstance(cmd, str) or not cmd.strip():
        return [err("tc-integration-command", "integration_test_command debe ser un string no vacío")]
    return []

def r_group_specs(ctx):
    """conforms_to/produces (opcionales): specs compartidas que el grupo consume/produce."""
    out = []
    for field in ("conforms_to", "produces"):
        v = ctx["fm"].get(field)
        if v is None:
            continue
        if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
            out.append(err("tc-group-specs", f"{field} debe ser una lista de rutas (string) a specs compartidas"))
    return out

# Un grupo NO se valida con las reglas de función (no tiene signature/target/budget/secciones).
# r_schema sí aplica: el schema discrimina por `kind` (rama group), así la FORMA queda cubierta.
GROUP_RULES = [r_schema, r_group_required, r_intent_atomic, r_group_children,
               r_integration_command, r_group_specs]


def lint(path):
    p = Path(path)
    fm, body = split_front_matter(p.read_text(encoding="utf-8"))
    if fm is None:
        return [err("tc-required", "sin front-matter YAML (--- ... ---)")]
    ctx = {"fm": fm, "body": body, "path": p, "budget": fm.get("budget") or {},
           "fn_name": None, "language": fm.get("language")}
    rules = GROUP_RULES if fm.get("kind") == "group" else RULES
    findings = []
    for rule in rules:
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
