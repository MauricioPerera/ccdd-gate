"""test_thresholds_sync.py — test de CONSISTENCIA congelado contrato<->código.

Evita el drift silencioso entre el contrato firmado (Ed25519) y los valores
hardcodeados en `runners/metrics_backends.py` (AMBER, RED, _SEVERITY_BANDS).

El contrato `contracts/complexity-agent/thresholds.txt` define en texto en
español las bandas verde/amarillo/rojo/crítico por métrica. Este test parsea
ese archivo de forma DETERMINISTA y afirma que:

  1) `AMBER[metric]` == cota inferior de la banda AMARILLA del contrato.
  2) `RED[metric]`   == cota inferior de la banda ROJA del contrato.
  3) `_SEVERITY_BANDS[metric]` == bandas (umbral, etiqueta) derivadas de las
     bandas ROJO y CRÍTICO del contrato (etiqueta extraída del paréntesis
     "reportar como <X>"), ordenadas de mayor a menor umbral.

Solo cubre las 4 métricas que el backend implementa: cyclomatic,
nesting_depth, parameter_count, function_length. Ignora complejidad cognitiva
y acoplamientos (no implementados en el backend).

El test pasa hoy y FALLA ante cualquier desincronización: si alguien cambia
`thresholds.txt` por quórum sin actualizar el código (o viceversa), o si el
parser no puede interpretar el nuevo formato, el test rompe.
"""
import re
import unittest
from pathlib import Path

import sys
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runners"))

import metrics_backends as mb  # noqa: E402

CONTRACT = REPO / "contracts" / "complexity-agent" / "thresholds.txt"

# Métricas que el backend implementa y el contrato describe. NO incluye
# complejidad cognitiva ni acoplamientos (el backend no las implementa).
METRICS = ("cyclomatic", "nesting_depth", "parameter_count", "function_length")

# Mapeo del encabezado del contrato (texto español) -> clave de métrica del backend.
SECTION_TO_METRIC = {
    "COMPLEJIDAD CICLOMÁTICA": "cyclomatic",
    "PROFUNDIDAD DE ANIDAMIENTO": "nesting_depth",
    "LONGITUD DE FUNCIÓN": "function_length",
    "NÚMERO DE PARÁMETROS DE FUNCIÓN": "parameter_count",
}

# Formato de línea de banda: "  <color>: <rango>   (<nota>)".
# Rango puede ser: "N–M" (en-dash U+2013 o hyphen), "≥ N", "> N", o un entero "N".
_BAND_RE = re.compile(
    r"^\s*(verde|amarillo|rojo|crítico)\s*:\s*([^()]+?)\s*(?:\(([^)]*)\))?\s*$"
)
_LABEL_RE = re.compile(r"reportar\s+como\s+([A-ZÁÉÍÓÚÑ]+)", re.IGNORECASE)


def _parse_bound(token):
    """Convierte un token de rango del contrato en el umbral numérico inferior.

    - "N–M" / "N-M" (en-dash o hyphen) -> N
    - "≥ N"                         -> N
    - "> N"                         -> N + 1   ("> 20" alcanza desde 21)
    - "N" (entero simple)           -> N

    Lanza ValueError si el token no encaja en ninguna forma conocida — así
    una edición del contrato que use una sintaxis nueva ROMPE el test en vez
    de pasar silenciosamente.
    """
    token = token.strip()
    m = re.match(r"^>=?\s*(\d+)$", token.replace("≥", ">="))
    if m:
        n = int(m.group(1))
        return n + 1 if token.startswith(">") else n
    m = re.match(r"^(\d+)\s*[–-]\s*(\d+)$", token)
    if m:
        return int(m.group(1))
    m = re.match(r"^(\d+)$", token)
    if m:
        return int(m.group(1))
    raise ValueError(f"token de umbral no reconocido: {token!r}")


def _parse_bands(text):
    """Parsea thresholds.txt -> {metric: {color: (bound_low, label|None)}}.

    Devuelve solo las métricas implementadas (las de SECTION_TO_METRIC).
    `label` es la etiqueta de severidad extraída del paréntesis "reportar como
    <X>" si existe, si no None (bandas verde/amarillo no la tienen).
    """
    bands = {}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        # ¿Encabezado de sección? (línea sin indentar que termina en ":"). Algunos
        # encabezados traen aclaraciones entre paréntesis antes del ":", p.ej.
        # "PROFUNDIDAD DE ANIDAMIENTO (niveles de indentación):", por eso
        # emparejamos por prefijo del nombre conocido (en MAYÚSCULAS) y no por
        # igualdad exacta.
        if not line.startswith(" ") and line.endswith(":"):
            name = line[:-1].strip().upper()
            current = None
            for key, metric in SECTION_TO_METRIC.items():
                if name.startswith(key):
                    current = metric
                    break
            continue
        if current is None:
            continue
        m = _BAND_RE.match(line)
        if not m:
            continue
        color, rng, note = m.group(1), m.group(2).strip(), m.group(3) or ""
        label = None
        lm = _LABEL_RE.search(note)
        if lm:
            label = lm.group(1).upper()
        bands.setdefault(current, {})[color] = (_parse_bound(rng), label)
    return bands


def _contract_severity_bands(bands):
    """Construye la lista (umbral, etiqueta) por métrica, espejo de _SEVERITY_BANDS.

    Reglas (espejo de thresholds.txt y de metrics_backends.py):
      - La banda CRÍTICO (si existe) aporta (umbral_crítico, etiqueta_crítico).
      - La banda ROJO aporta (umbral_rojo, etiqueta_rojo).
      - Solo bandas con etiqueta de severidad (las que "reportan").
      - Ordenadas de mayor a menor umbral (la primera que se alcanza gana).
    """
    out = {}
    for metric, color_map in bands.items():
        pairs = []
        for color in ("crítico", "rojo"):
            if color not in color_map:
                continue
            bound, label = color_map[color]
            if label is None:
                continue
            pairs.append((bound, label))
        pairs.sort(key=lambda t: t[0], reverse=True)
        out[metric] = pairs
    return out


class TestThresholdsSync(unittest.TestCase):
    """Congela la consistencia contrato<->código para las 4 métricas implementadas."""

    @classmethod
    def setUpClass(cls):
        assert CONTRACT.exists(), f"contrato firmado no encontrado: {CONTRACT}"
        cls.bands = _parse_bands(CONTRACT.read_text(encoding="utf-8"))
        # Toda métrica implementada debe estar descrita en el contrato.
        for metric in METRICS:
            assert metric in cls.bands, f"métrica {metric} ausente en el contrato"
            for color in ("amarillo", "rojo"):
                assert color in cls.bands[metric], (
                    f"banda {color} de {metric} ausente en el contrato"
                )

    def test_amber_matches_contract_yellow_low(self):
        """AMBER == cota inferior de la banda AMARILLA por métrica."""
        for metric in METRICS:
            with self.subTest(metric=metric):
                expected = self.bands[metric]["amarillo"][0]
                self.assertEqual(mb.AMBER[metric], expected)

    def test_red_matches_contract_red_low(self):
        """RED == cota inferior de la banda ROJA por métrica."""
        for metric in METRICS:
            with self.subTest(metric=metric):
                expected = self.bands[metric]["rojo"][0]
                self.assertEqual(mb.RED[metric], expected)

    def test_severity_bands_match_contract(self):
        """_SEVERITY_BANDS == bandas (umbral, etiqueta) derivadas del contrato."""
        expected = _contract_severity_bands(self.bands)
        for metric in METRICS:
            with self.subTest(metric=metric):
                self.assertEqual(
                    mb._SEVERITY_BANDS[metric],
                    expected.get(metric, []),
                )


if __name__ == "__main__":
    unittest.main()