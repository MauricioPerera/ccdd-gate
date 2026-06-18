"""metrics.py — backend DETERMINISTA de métricas de complejidad para PYTHON (stdlib, sin deps).

Primer backend del registro pluggable (ver `metrics_backends.py`): mide ciclomática, profundidad
de anidamiento, nº de parámetros y longitud por función desde el AST de Python. La severidad, los
umbrales y el ensamblado de `lint_results` (conforme a lint_results.schema.json) son COMPARTIDOS
por todos los lenguajes y viven en `metrics_backends`; aquí solo está la extracción Python.

El LLM razona ESENCIAL/ACCIDENTAL ENCIMA de estos números reales (no los estima).

API pública estable (back-compat, sin cambios de comportamiento):
  - functions_metrics(src) -> métricas crudas por función (base del budget-gate)
  - extract_source(src, name) -> lint_results
  - extract(path) -> lint_results de un archivo
  - severity(metric, v) -> severidad (re-export de la capa compartida)
"""
import ast
from pathlib import Path

import metrics_backends as _mb
from metrics_backends import severity, build_findings, AMBER as _AMBER, RED as _RED  # noqa: F401

_DECISION = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)
_NEST = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)

_TOOL = "ccdd-ast-metrics"
_VERSION = "1"


def _cyclomatic(node):
    # ifs planos (no elif): los tipos son disjuntos -> mismo resultado, sin anidamiento de AST
    c = 1
    for n in ast.walk(node):
        if isinstance(n, _DECISION):
            c += 1
        if isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        if isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
        if isinstance(n, ast.match_case):
            c += 1
    return c


def _params(node):
    a = node.args
    return (len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
            + (1 if a.vararg else 0) + (1 if a.kwarg else 0))


def _nesting(node, depth=0):
    best = depth
    for child in ast.iter_child_nodes(node):
        d = depth + 1 if isinstance(child, _NEST) else depth
        best = max(best, _nesting(child, d))
    return best


def functions_metrics(src):
    """Métricas de TODAS las funciones (sin filtrar por umbral) — para el gate por-budget."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({"function": node.name, "line": node.lineno,
                        "cyclomatic": _cyclomatic(node), "nesting_depth": _nesting(node),
                        "parameter_count": _params(node),
                        "function_length": getattr(node, "end_lineno", node.lineno) - node.lineno + 1})
    return out


def extract_source(src, name="snippet.py"):
    """Mide complejidad por AST sobre código en string. Conforme a lint_results.schema.json."""
    try:
        funcs = functions_metrics(src)
    except SyntaxError as e:
        return {"tool": _TOOL, "version": _VERSION, "timestamp": _mb._ts(),
                "findings": [], "parse_error": str(e)}
    return build_findings(funcs, name, _TOOL, _VERSION)


def extract(path):
    """Devuelve un dict conforme a lint_results.schema.json para un archivo .py."""
    p = Path(path)
    return extract_source(p.read_text(encoding="utf-8"), p.name)


class PythonBackend(_mb.Backend):
    """Backend de métricas para Python (AST de la stdlib)."""
    language = "python"
    extensions = (".py", ".pyi")
    tool = _TOOL
    version = _VERSION

    def measure(self, src):
        return functions_metrics(src)

    def extract_source(self, src, filename="snippet.py"):
        # delega en el helper del módulo, que captura SyntaxError -> parse_error (back-compat)
        return extract_source(src, filename)


_mb.register(PythonBackend())
