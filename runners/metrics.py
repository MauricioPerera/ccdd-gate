"""metrics.py — extractor DETERMINISTA de métricas de complejidad por AST (stdlib, sin deps).

Provee el slot `lint_results` del contrato complexity-agent sin depender de un linter externo:
mide ciclomática, profundidad de anidamiento, nº de parámetros y longitud por función desde el
AST de Python. Salida conforme a lint_results.schema.json. El LLM razona ESENCIAL/ACCIDENTAL
ENCIMA de estos números reales (no los estima)."""
import ast
import datetime
from pathlib import Path

# "amarillo": a partir de aquí vale la pena reportar al LLM. "rojo": threshold del finding.
_AMBER = {"cyclomatic": 6, "nesting_depth": 3, "parameter_count": 4, "function_length": 21}
_RED = {"cyclomatic": 11, "nesting_depth": 4, "parameter_count": 6, "function_length": 41}
_DECISION = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)
_NEST = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def severity(metric, v):
    """Severidad DETERMINISTA por métrica, espejo de thresholds.txt (contrato firmado).
    Es la base del gate duro: idéntica corrida a corrida, sin depender del LLM."""
    if metric == "cyclomatic":
        return "CRÍTICA" if v > 20 else "ALTA" if v >= 11 else "INFO"
    if metric == "nesting_depth":
        return "CRÍTICA" if v >= 5 else "ALTA" if v >= 4 else "INFO"
    if metric == "function_length":
        return "ALTA" if v > 80 else "MEDIA" if v >= 41 else "INFO"
    if metric == "parameter_count":
        return "MEDIA" if v >= 6 else "INFO"
    return "INFO"


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
    out = {"tool": "ccdd-ast-metrics", "version": "1", "timestamp": _ts(), "findings": []}
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        out["parse_error"] = str(e)
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        vals = {
            "cyclomatic": _cyclomatic(node),
            "nesting_depth": _nesting(node),
            "parameter_count": _params(node),
            "function_length": getattr(node, "end_lineno", node.lineno) - node.lineno + 1,
        }
        for metric, value in vals.items():
            if value >= _AMBER[metric]:
                out["findings"].append({
                    "file": name, "line": node.lineno, "metric": metric,
                    "value": value, "threshold": _RED[metric], "function": node.name,
                    "exceeds_threshold": value >= _RED[metric],
                    "severity": severity(metric, value),
                })
    return out


def extract(path):
    """Devuelve un dict conforme a lint_results.schema.json para un archivo .py."""
    p = Path(path)
    return extract_source(p.read_text(encoding="utf-8"), p.name)
