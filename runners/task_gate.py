#!/usr/bin/env python3
"""task_gate.py — veredicto DETERMINISTA unificado de una task. Sin LLM.
  0) el contrato lintea (tc_lint)
  1) gate complejidad: la función implementada ≤ budget de la task
  2) gate corrección: los property-tests congelados pasan
PASS solo si las tres. Idéntico corrida a corrida.

Uso:  python task_gate.py task.md
Exit: 0 PASS · 1 FAIL · 2 contrato inválido."""
import ast
import builtins
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402
import metrics_backends  # noqa: E402
import deps_check  # noqa: E402  (enforcement OPT-IN de deps_allowed)
import sig_check  # noqa: E402  (conformidad de firma implementada vs contrato)
import purity_check  # noqa: E402  (gate de pureza OPT-IN: impurezas del cuerpo)
import mutdef_check  # noqa: E402  (gate de defaults mutables OPT-IN: forbid_mutable_defaults)
import bareexcept_check  # noqa: E402  (gate de except desnudo OPT-IN: forbid_bare_except)
import assert_check  # noqa: E402  (gate de asserts en producción OPT-IN: forbid_assert)
import nonecmp_check  # noqa: E402  (gate de comparación con None por ==/!= OPT-IN: forbid_none_eq)

BUDGET_KEY = {"cyclomatic": "cyclomatic_max", "nesting_depth": "nesting_max",
              "parameter_count": "params_max", "function_length": "lines_max"}


# gate 0.5 — OK humano (determinista, a prueba de manipulación): si el contrato exige
# aprobación, los bytes de los tests deben coincidir con el hash que firmó el humano.
def _gate_test_approval(fm, tests):
    if not fm.get("require_test_approval"):
        return None
    if not tests.exists():
        return {"verdict": "INVALID", "stage": "test-approval", "detail": f"tests no existe: {fm['tests']}"}
    actual = hashlib.sha256(tests.read_bytes()).hexdigest()
    approved = fm.get("tests_sha256")
    if not approved:
        return {"verdict": "INVALID", "stage": "test-approval",
                "detail": "tests sin aprobar (falta tests_sha256). Revisa con test_audit.py y firma con approve_tests.py.",
                "tests_sha256_actual": actual}
    if actual != approved:
        return {"verdict": "INVALID", "stage": "test-approval",
                "detail": "los tests cambiaron desde la aprobación (hash no coincide). Re-audita y re-aprueba.",
                "approved": approved, "actual": actual}
    return None


# CWD para correr los tests. Default histórico (a prueba de regresión): la carpeta del target.
# Si el contrato declara `test_cwd`, se resuelve relativo al directorio del contrato (igual que
# target/tests), permitiendo correr los tests desde la raíz del proyecto sin paths absolutos.
def _resolve_test_cwd(fm, target, contract_dir):
    tc = fm.get("test_cwd")
    if tc:
        return str((contract_dir / tc).resolve())
    return str(target.parent)


# gate 1 — property-tests congelados (determinista) y sintaxis
def _gate_run_tests(fm, target, tests, contract_dir):
    if not tests.exists():
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": f"tests no existe: {fm['tests']}"}
    test_cmd_str = fm.get("test_command")
    # shlex.split + sin shell: comando portable y determinista. Respeta comillas (simples y dobles)
    # igual en todas las plataformas, a diferencia de shell=True que en Windows usa cmd.exe y rompe
    # las comillas simples (causa de los fallos con rutas con espacios).
    cmd = shlex.split(test_cmd_str) if test_cmd_str else [sys.executable, str(tests.resolve())]
    cwd = _resolve_test_cwd(fm, target, contract_dir)
    if not Path(cwd).is_dir():
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": f"el cwd de tests no existe: {cwd}"}
    r = subprocess.run(cmd, cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        # `cwd` en el detalle: si el comando no encuentra el test, el autor ve desde DÓNDE corrió
        # (los paths del test_command son relativos a esto) y puede ajustar test_cwd sin adivinar.
        return {"verdict": "FAIL", "stage": "gate1-tests", "detail": "property-tests o sintaxis fallaron",
                "cwd": cwd, "output": (r.stderr or r.stdout or "")[-800:]}
    return None


# Selección de la función objetivo entre las que comparten nombre. Resolver por nombre con un dict
# es last-wins: con métodos homónimos en varias clases (set/get/search/__init__…) mide el equivocado
# y da un PASS/FAIL engañoso (issue #41). Por eso: si hay >1 def del nombre se exige `target_line`
# (la línea es única por def y la exponen todos los backends); sin desambiguador, INVALID, nunca medir
# la última en silencio. Con un solo match el comportamiento es idéntico al histórico (back-compat).
def _select_target_fn(fm, fn_name, matches, target_name):
    if not matches:
        return {"verdict": "FAIL", "stage": "gate2-complexity",
                "detail": f"la función '{fn_name}' no está en {target_name}"}
    line = fm.get("target_line")
    if line is not None:
        hit = [m for m in matches if m["line"] == line]
        if not hit:
            return {"verdict": "INVALID", "stage": "gate2-complexity",
                    "detail": f"target_line={line} no coincide con ninguna def de '{fn_name}' en {target_name}",
                    "candidate_lines": sorted(m["line"] for m in matches)}
        return hit[0]
    if len(matches) > 1:
        return {"verdict": "INVALID", "stage": "gate2-complexity",
                "detail": f"la firma '{fn_name}' es ambigua: {len(matches)} definiciones en {target_name}; "
                          f"añade target_line para desambiguar",
                "candidate_lines": sorted(m["line"] for m in matches)}
    return matches[0]


# gate 2 — complejidad ≤ budget de la task
def _gate_complexity(fm, target, fn_name, budget):
    if not target.exists():
        return {"verdict": "FAIL", "stage": "gate2-complexity", "detail": f"target no existe: {fm['target']}"}
    all_fns = metrics_backends.functions_metrics(target.read_text(encoding="utf-8"), language=fm.get("language"), filename=str(target))
    m = _select_target_fn(fm, fn_name, [f for f in all_fns if f["function"] == fn_name], fm["target"])
    if "verdict" in m:  # dict de error (FAIL/INVALID), no una fila de métricas
        return m
    over = [f"{metric}={m[metric]} > {key}={budget[key]}"
            for metric, key in BUDGET_KEY.items()
            if isinstance(budget.get(key), int) and m[metric] > budget[key]]
    if over:
        return {"verdict": "FAIL", "stage": "gate2-complexity", "function": fn_name, "over_budget": over}
    return {"verdict": "PASS", "stage": "all", "function": fn_name,
            "metrics": {k: m[k] for k in BUDGET_KEY}, "budget": budget}


# --- Gate de integración (contratos de GRUPO) -------------------------------------------------
# Un contrato con `kind: group` compone funciones (u otros grupos) hijas. PASS solo si TODAS las
# hijas pasan su propio gate Y los tests de integración (la composición ensamblada) pasan. Es
# recursivo: una hija puede ser otro grupo, modelando spec -> task -> función. Determinista.
MAX_GROUP_DEPTH = 10


def _resolve_group_cwd(fm, group_dir):
    tc = fm.get("test_cwd")
    return str((group_dir / tc).resolve()) if tc else str(group_dir)


def _gate_children(fm, group_dir, depth):
    children = fm.get("children")
    if not isinstance(children, list) or not children:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": "un contrato 'group' requiere 'children' (lista no vacía)"}
    for child in children:
        cp = group_dir / child
        if not cp.exists():
            return {"verdict": "INVALID", "stage": "integration-contract",
                    "detail": f"contrato hijo no existe: {child}"}
        v = gate(str(cp), depth + 1)
        if v.get("verdict") != "PASS":
            return {"verdict": "FAIL", "stage": "integration-children",
                    "failed_child": child, "child_verdict": v}
    return None


def _gate_integration_tests(fm, group_dir):
    cmd_str = fm.get("integration_test_command")
    if not cmd_str:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": "un contrato 'group' requiere integration_test_command"}
    itests = fm.get("integration_tests")
    if itests and not (group_dir / itests).exists():
        return {"verdict": "FAIL", "stage": "integration-tests",
                "detail": f"integration_tests no existe: {itests}"}
    cwd = _resolve_group_cwd(fm, group_dir)
    if not Path(cwd).is_dir():
        return {"verdict": "FAIL", "stage": "integration-tests", "detail": f"el cwd de integración no existe: {cwd}"}
    r = subprocess.run(shlex.split(cmd_str), cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        return {"verdict": "FAIL", "stage": "integration-tests", "cwd": cwd,
                "output": (r.stderr or r.stdout or "")[-800:]}
    return None


# Spec compartida (zero-dep): un grupo declara las specs que CONSUME (`conforms_to`) o PRODUCE
# (`produces`). El gate verifica que existan y estén BIEN FORMADAS. La alineación backend<->front
# se garantiza porque ambos apuntan al MISMO archivo (misma verdad). La conformidad de COMPORTAMIENTO
# (¿la API servida cumple el OpenAPI?) es el integration_test_command (validador pluggable, opcional).
def _spec_wellformed(path):
    if not path.exists():
        return f"spec compartida no existe: {path.name}"
    suf = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
        if suf in (".yaml", ".yml"):
            import yaml
            yaml.safe_load(text)
        elif suf == ".json":
            json.loads(text)
    except Exception as e:
        return f"spec compartida mal formada ({path.name}): {e}"
    return None


def _gate_spec_conformance(fm, group_dir):
    refs = list(fm.get("conforms_to") or []) + list(fm.get("produces") or [])
    for ref in refs:
        problem = _spec_wellformed(group_dir / ref)
        if problem:
            return {"verdict": "FAIL", "stage": "integration-spec", "detail": problem}
    return None


def integration_gate(group_path, fm, depth=0):
    if depth > MAX_GROUP_DEPTH:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": f"recursión de grupos > {MAX_GROUP_DEPTH}; ¿ciclo en children?"}
    missing = [k for k in ("task", "intent", "children", "integration_test_command") if k not in fm]
    if missing:
        return {"verdict": "INVALID", "stage": "integration-contract",
                "detail": f"contrato 'group' incompleto, faltan: {missing}"}
    group_dir = Path(group_path).parent
    return (_gate_children(fm, group_dir, depth)
            or _gate_spec_conformance(fm, group_dir)
            or _gate_integration_tests(fm, group_dir)
            or {"verdict": "PASS", "stage": "integration-all", "children": fm["children"]})


# gate 3 — nombres de anotaciones resueltos (Python). Caza el bug que el runtime ENMASCARA: un
# nombre usado en una anotación sin importarlo/definirlo (p.ej. `x: Node` sin `import Node`). En
# Python 3.14 las lazy annotations lo dejan pasar en runtime, pero rompe en <3.14 y es incorrecto.
# Determinista, zero-dep (AST puro), independiente de la versión de Python. Solo aplica a Python.
def _type_param_names(node):
    """Nombres de los type_params PEP 695 (def f[T], class C[T], type X[T]). [] si no hay."""
    return [tp.name for tp in getattr(node, "type_params", [])]


def _names_from_node(node):
    """Nombres que un nodo define (import/def/clase/asignación/type-alias). Lista (posible vacía),
    o None si es un `from x import *` (no analizable de forma segura). Permisivo a propósito: ante
    la duda incluye de más (evita falsos positivos en un gate default-on)."""
    if isinstance(node, ast.Import):
        return [(a.asname or a.name).split(".")[0] for a in node.names]
    if isinstance(node, ast.ImportFrom):
        if any(a.name == "*" for a in node.names):
            return None
        return [a.asname or a.name for a in node.names]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name, *_type_param_names(node)]
    if isinstance(node, ast.Assign):  # incluye desempaquetado: A, B = ... ; (a[0], obj.x) = ...
        return [n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):  # PEP 695: type X = ...
        return [node.name.id, *_type_param_names(node)]
    return []


def _defined_names(tree):
    """Nombres definidos en cualquier scope del módulo. None si hay `from x import *` (no se
    reporta nada en ese caso)."""
    names = set()
    for node in ast.walk(tree):
        got = _names_from_node(node)
        if got is None:
            return None
        names.update(got)
    return names


def _annotation_name_refs(tree):
    """Nombres (ast.Name) referenciados en cualquier anotación: args, return, AnnAssign. Las
    forward-refs en string NO se incluyen (son Constant, no Name)."""
    refs = set()
    for node in ast.walk(tree):
        anns = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            anns = [ar.annotation for ar in (a.posonlyargs + a.args + a.kwonlyargs)]
            anns += [a.vararg.annotation if a.vararg else None, a.kwarg.annotation if a.kwarg else None, node.returns]
        elif isinstance(node, ast.AnnAssign):
            anns = [node.annotation]
        for ann in anns:
            if ann is not None:
                refs.update(n.id for n in ast.walk(ann) if isinstance(n, ast.Name))
    return refs


def _gate_annotations(fm, target):
    if (fm.get("language") or "python").lower() != "python":
        return None
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except Exception:
        return None  # la sintaxis ya la pesca el gate de tests
    defined = _defined_names(tree)
    if defined is None:
        return None  # star import: no analizable
    known = defined | set(dir(builtins))
    undefined = sorted(r for r in _annotation_name_refs(tree) if r not in known)
    if undefined:
        return {"verdict": "FAIL", "stage": "gate3-annotations",
                "detail": f"nombres usados en anotaciones sin importar/definir: {undefined}"}
    return None


# gate 3.5 — conformidad de firma IMPLEMENTADA vs la `signature` del contrato (DEFAULT-ON para toda
# función con signature). Compara nombre + nombres de parámetros en orden (ignora anotaciones y
# defaults). Un desajuste -> FAIL antes de medir complejidad: mide la firma equivocada da PASS/FAIL
# engañoso. Determinista, zero-dep (AST puro). Si el target no existe, deja que lo reporte
# _gate_complexity (back-compat: no duplica el error).
def _gate_signature(fm, target, fn_name):
    if not target.exists():
        return None
    source = target.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None  # la sintaxis la pesca gate1-tests
    # Si la función (en target_line, si se da) no es resoluble, CEDE: que _gate_complexity emita el
    # diagnóstico preciso (FAIL "no está" / INVALID "ambiguo" con candidate_lines). gate-signature
    # solo juzga el desajuste de una firma RESOLUBLE, no la validez del target_line.
    if sig_check._find_function(tree, fn_name, fm.get("target_line")) is None:
        return None
    m = sig_check.signature_mismatch(source, fn_name, fm["signature"], target_line=fm.get("target_line"))
    if m:
        return {"verdict": "FAIL", "stage": "gate-signature", "mismatch": m}
    return None


# gate 3.6 — pureza OPT-IN. Solo corre si el contrato declara `pure: true`: el cuerpo de la
# función NO debe tener operaciones impuras (print/open/eval/global/import/...). Lee el source del
# target y calcula las marcas con purity_check.impure_operations. Determinista, sin LLM. Si el
# target no existe, deja que lo reporte _gate_complexity (back-compat: no duplica el error).
def _gate_purity(fm, target, fn_name):
    if not fm.get("pure"):
        return None
    if not target.exists():
        return None
    imp = purity_check.impure_operations(target.read_text(encoding="utf-8"), fn_name, fm.get("target_line"))
    if imp:
        return {"verdict": "FAIL", "stage": "gate-purity", "impurities": imp}
    return None


# gate 3.7 — defaults mutables OPT-IN. Solo corre si el contrato declara
# `forbid_mutable_defaults: true`: los parámetros con default mutable (list/dict/set literal o
# Call a list/dict/set) son un bug clásico (comparten estado entre llamadas). Lee el source del
# target y calcula los nombres con mutdef_check.mutable_defaults. Determinista, sin LLM. Si el
# target no existe, deja que lo reporte _gate_complexity (back-compat: no duplica el error).
def _gate_mutdef(fm, target, fn_name):
    if not fm.get("forbid_mutable_defaults"):
        return None
    if not target.exists():
        return None
    md = mutdef_check.mutable_defaults(target.read_text(encoding="utf-8"), fn_name, fm.get("target_line"))
    if md:
        return {"verdict": "FAIL", "stage": "gate-mutdef", "mutable_defaults": md}
    return None


# gate 3.8 — except desnudo OPT-IN. Solo corre si el contrato declara
# `forbid_bare_except: true`: los `except:` sin tipo (bare) tragan KeyboardInterrupt/SystemExit y
# enmascaran bugs. Lee el source del target y calcula las líneas con
# bareexcept_check.bare_except_lines. Determinista, sin LLM. Si el target no existe, deja que lo
# reporte _gate_complexity (back-compat: no duplica el error).
def _gate_bareexcept(fm, target, fn_name):
    if not fm.get("forbid_bare_except"):
        return None
    if not target.exists():
        return None
    be = bareexcept_check.bare_except_lines(target.read_text(encoding="utf-8"), fn_name, fm.get("target_line"))
    if be:
        return {"verdict": "FAIL", "stage": "gate-bareexcept", "bare_except_lines": be}
    return None


# gate 3.9 — asserts en producción OPT-IN. Solo corre si el contrato declara
# `forbid_assert: true`: los `assert` en código de producción se eliminan con -O y dejan de
# verificar invariantes; son herramientas de test, no de runtime. Lee el source del target y
# calcula las líneas con assert_check.assert_lines. Determinista, sin LLM. Si el target no
# existe, deja que lo reporte _gate_complexity (back-compat: no duplica el error).
def _gate_assert(fm, target, fn_name):
    if not fm.get("forbid_assert"):
        return None
    if not target.exists():
        return None
    al = assert_check.assert_lines(target.read_text(encoding="utf-8"), fn_name, fm.get("target_line"))
    if al:
        return {"verdict": "FAIL", "stage": "gate-assert", "assert_lines": al}
    return None


# gate 3.10 — comparación con None por ==/!= OPT-IN. Solo corre si el contrato declara
# `forbid_none_eq: true`: comparar con None usando ==/!= es un antipatrón (PEP 8 recomienda
# `is`/`is not`); además `==` puede invocar __eq__ de subtipos y dar resultados inesperados.
# Lee el source del target y calcula las líneas con nonecmp_check.none_eq_lines. Determinista,
# sin LLM. Si el target no existe, deja que lo reporte _gate_complexity (back-compat: no duplica).
def _gate_nonecmp(fm, target, fn_name):
    if not fm.get("forbid_none_eq"):
        return None
    if not target.exists():
        return None
    ne = nonecmp_check.none_eq_lines(target.read_text(encoding="utf-8"), fn_name, fm.get("target_line"))
    if ne:
        return {"verdict": "FAIL", "stage": "gate-nonecmp", "none_eq_lines": ne}
    return None


# gate 4 — enforcement OPT-IN de deps_allowed (anti-slopsquatting). Solo corre si el contrato
# declara `enforce_deps: true`. Lee el source del target y flaggea imports top-level que no estén
# en deps_allowed (ni en stdlib). Determinista, sin LLM. Si el target no existe, deja que lo
# reporte _gate_complexity (back-compat: no duplica el error).
def _gate_deps(fm, target):
    if not fm.get("enforce_deps"):
        return None
    if not target.exists():
        return None
    unauthorized = deps_check.unauthorized_imports(
        target.read_text(encoding="utf-8"), fm.get("deps_allowed") or [])
    if unauthorized:
        return {"verdict": "FAIL", "stage": "gate-deps", "unauthorized": unauthorized}
    return None


def gate(task_path, _depth=0):
    p = Path(task_path)
    fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
    if any(f["level"] == "error" for f in tc_lint.lint(task_path)):
        return {"verdict": "INVALID", "stage": "contract",
                "detail": "el task-contract no lintea (corre tc_lint.py para el detalle)"}
    if fm.get("kind") == "group":
        return integration_gate(task_path, fm, _depth)
    target = p.parent / fm["target"]
    tests = p.parent / fm["tests"]
    fn_name, _n = tc_lint.parse_sig(fm["signature"], fm.get("language"))

    return (_gate_test_approval(fm, tests)
            or _gate_run_tests(fm, target, tests, p.parent)
            or _gate_annotations(fm, target)
            or _gate_signature(fm, target, fn_name)
            or _gate_purity(fm, target, fn_name)
            or _gate_mutdef(fm, target, fn_name)
            or _gate_bareexcept(fm, target, fn_name)
            or _gate_assert(fm, target, fn_name)
            or _gate_nonecmp(fm, target, fn_name)
            or _gate_deps(fm, target)
            or _gate_complexity(fm, target, fn_name, fm["budget"]))


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if len(sys.argv) < 2:
        print("uso: python task_gate.py task.md", file=sys.stderr)
        return 2
    v = gate(sys.argv[1])
    print(json.dumps(v, ensure_ascii=False, indent=2))
    return 0 if v["verdict"] == "PASS" else (2 if v["verdict"] == "INVALID" else 1)


if __name__ == "__main__":
    sys.exit(main())
