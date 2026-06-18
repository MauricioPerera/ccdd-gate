"""metrics_backends.py — capa NEUTRAL compartida + registro de backends de métricas por lenguaje.

El concepto de las cuatro métricas es independiente del lenguaje; lo único atado a un lenguaje
es la EXTRACCIÓN (parsear el código y contar). Este módulo define:

  1) la definición NEUTRAL de cada métrica (doc, abajo),
  2) los umbrales firmados y `severity()` — COMPARTIDOS por todos los lenguajes (no se duplican),
  3) el ensamblado de `lint_results` (conforme a lint_results.schema.json) — compartido,
  4) un registro `register()` / `get_backend()` que enruta por lenguaje o extensión.

Un backend SOLO mide: implementa `measure(src) -> [métricas crudas por función]`. La severidad,
los umbrales y el shape de salida salen de aquí, así que añadir un lenguaje = registrar un backend
sin tocar gate/runner/MCP. Determinista, sin LLM.

Definición neutral de las métricas (idéntica entre lenguajes salvo divergencias documentadas):
  - cyclomatic       = 1 + decisiones (if/for/while/except/ternario)
                         + (operandos_booleanos − 1) por cada cadena and/or
                         + comprehensions (+1 por cada `if` de filtro)
                         + ramas de match/switch
  - nesting_depth    = profundidad máxima de bloques que anidan (if/for/while/with/try/…)
  - parameter_count  = aridad de la firma (incluye *args/**kwargs como 1 cada uno)
  - function_length  = líneas de la función (última − primera + 1)

Métricas crudas por función — shape que devuelve `measure(src)` (y que consume el budget-gate):
  {"function": str, "line": int>=1,
   "cyclomatic": int, "nesting_depth": int, "parameter_count": int, "function_length": int}
"""
import datetime

# "amarillo": a partir de aquí vale la pena reportar al LLM. "rojo": threshold del finding.
# Únicos y compartidos por TODOS los lenguajes (espejo de thresholds.txt, contrato firmado).
AMBER = {"cyclomatic": 6, "nesting_depth": 3, "parameter_count": 4, "function_length": 21}
RED = {"cyclomatic": 11, "nesting_depth": 4, "parameter_count": 6, "function_length": 41}

# Orden canónico de métricas — fija el orden de los findings (determinismo, regresión cero).
METRIC_KEYS = ("cyclomatic", "nesting_depth", "parameter_count", "function_length")


def _ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def severity(metric, v):
    """Severidad DETERMINISTA por métrica, espejo de thresholds.txt (contrato firmado).
    Compartida entre lenguajes: es la base del gate duro, idéntica corrida a corrida."""
    if metric == "cyclomatic":
        return "CRÍTICA" if v > 20 else "ALTA" if v >= 11 else "INFO"
    if metric == "nesting_depth":
        return "CRÍTICA" if v >= 5 else "ALTA" if v >= 4 else "INFO"
    if metric == "function_length":
        return "ALTA" if v > 80 else "MEDIA" if v >= 41 else "INFO"
    if metric == "parameter_count":
        return "MEDIA" if v >= 6 else "INFO"
    return "INFO"


def build_findings(funcs, filename, tool, version, timestamp=None):
    """Ensambla `lint_results` (conforme a lint_results.schema.json) desde métricas crudas.
    Compartido por todos los backends: reporta una métrica solo si entra en AMBER. El orden
    de findings sigue `funcs` y `METRIC_KEYS` (determinista)."""
    out = {"tool": tool, "version": version, "timestamp": timestamp or _ts(), "findings": []}
    for f in funcs:
        for metric in METRIC_KEYS:
            value = f[metric]
            if value >= AMBER[metric]:
                out["findings"].append({
                    "file": filename, "line": f["line"], "metric": metric,
                    "value": value, "threshold": RED[metric], "function": f["function"],
                    "exceeds_threshold": value >= RED[metric],
                    "severity": severity(metric, value),
                })
    return out


# ── Registro de backends ──────────────────────────────────────────────────────────────────
_BY_LANG = {}   # "python" -> backend
_BY_EXT = {}    # ".py"     -> backend
DEFAULT_LANGUAGE = "python"


class Backend:
    """Interfaz de un backend de métricas. Subclasea y define `measure`.

    Atributos requeridos:
      language    str             — nombre canónico ("python", "typescript", …)
      extensions  tuple[str, ...] — extensiones que enruta (".py", …), con el punto
      tool        str             — nombre que va en lint_results["tool"]
      version     str             — versión que va en lint_results["version"]
    """
    language = ""
    extensions = ()
    tool = "ccdd-metrics"
    version = "1"

    def measure(self, src):
        """src:str -> lista de métricas crudas por función (ver shape arriba)."""
        raise NotImplementedError

    def extract_source(self, src, filename="snippet"):
        """lint_results completo para `src`. Reusa el ensamblado compartido."""
        return build_findings(self.measure(src), filename, self.tool, self.version)


def register(backend):
    """Registra un backend por su `language` y cada una de sus `extensions`. Idempotente."""
    _BY_LANG[backend.language] = backend
    for ext in backend.extensions:
        normalized_ext = ext.lower() if ext.startswith(".") else "." + ext.lower()
        _BY_EXT[normalized_ext] = backend
    return backend


def _ensure_builtins():
    # El backend Python vive en metrics.py y se registra al importarse. Import perezoso para
    # evitar dependencia circular en tiempo de carga del módulo.
    if DEFAULT_LANGUAGE not in _BY_LANG:
        import metrics  # noqa: F401


def get_backend(language=None, extension=None, filename=None):
    """Punto ÚNICO de resolución de backend. Precedencia: language explícito > extension >
    extensión derivada de filename > DEFAULT_LANGUAGE (python, back-compat).

    Lanza KeyError si se pide un lenguaje/extensión sin backend registrado (no-op silencioso
    no: el caller decide cómo degradar — ver issues #4/#5)."""
    _ensure_builtins()
    if language:
        return _BY_LANG[language]
    import os
    ext = extension
    if not ext and filename:
        basename = os.path.basename(filename)
        if "." in basename:
            ext = "." + basename.rsplit(".", 1)[1]
    if ext:
        return _BY_EXT[ext.lower()]
    return _BY_LANG[DEFAULT_LANGUAGE]


def supported_languages():
    """Lenguajes con backend registrado (para diagnósticos/dispatch)."""
    _ensure_builtins()
    return sorted(_BY_LANG)


def supported_extensions():
    """Extensiones con backend registrado (para diagnósticos/dispatch)."""
    _ensure_builtins()
    return sorted(_BY_EXT)


# ── Helpers genéricos enrutados por lenguaje (los usarán gate/runner/MCP en #4/#5) ──────────
def functions_metrics(src, language=None, extension=None, filename=None):
    """Métricas crudas por función usando el backend del lenguaje indicado (default python)."""
    return get_backend(language, extension, filename).measure(src)


def extract_source(src, filename="snippet", language=None, extension=None):
    """lint_results usando el backend del lenguaje indicado (default python)."""
    return get_backend(language, extension, filename or None).extract_source(src, filename)
