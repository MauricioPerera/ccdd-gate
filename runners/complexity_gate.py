#!/usr/bin/env python3
"""complexity_gate.py — gate DETERMINISTA de complejidad. Sirve como CLI o como hook
PostToolUse de Claude Code (loop de auto-validación tras escribir un archivo).

Mide el archivo con el backend del LENGUAJE (por extensión o `--language`; default python) y,
si alguna métrica entra en CRÍTICA (umbrales firmados), falla y pide refactor. NO usa LLM: el
veredicto es función pura del código (estable corrida a corrida).

Uso CLI:   python complexity_gate.py archivo.py [--language LANG]
Uso hook:  recibe el JSON del tool por stdin (tool_input.file_path) y emite feedback por stderr.
Exit: 0 sin CRÍTICA (o sin backend para la extensión: no-op anunciado) · 2 hay CRÍTICA
(en hook, stderr se devuelve al agente como motivo de refactor).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402  (registra el backend python al importarse)
import metrics_backends as mb  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def cli_flag(name):
    for i, a in enumerate(sys.argv[1:]):
        if a == name and i + 2 <= len(sys.argv[1:]):
            return sys.argv[1:][i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def target_path():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return args[0]
    try:  # modo hook: Claude Code pasa el evento por stdin
        data = json.load(sys.stdin)
        return (data.get("tool_input") or {}).get("file_path")
    except Exception:
        return None


def resolve_backend(path):
    """Backend por --language explícito o por la extensión del archivo. None (con aviso) si no hay."""
    try:
        return mb.get_backend(language=cli_flag("--language"), filename=os.path.basename(path))
    except KeyError:
        print(f"[complexity-gate] sin backend de métricas para {os.path.basename(path)} "
              f"(lenguajes disponibles: {', '.join(mb.supported_languages())}). No-op, no bloquea.",
              file=sys.stderr)
        return None


EXEMPTION_SLOT = "complexity_exception"
# Target firmado por el revisor: el mensaje Ed25519 es f"{EXEMPTION_SLOT}:{hash}".
# Debe coincidir con review_attestations.EXEMPTION_SLOT — firma y verificación usan el
# MISMO slot, o la firma no verifica.


def _load_json(path):
    """JSON del path o None si no existe / no parsea (defensivo, sin traceback)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _is_exempt(code_str, ext, contract_dir=None):
    """(exento, hash) — exento SÓLO si una excepción FIRMADA (Ed25519) por un revisor
    REGISTRADO cubre el hash semántico del código. Sin firma válida → NO exento.

    Hash: semantic_hash.get_semantic_hash — el MISMO que usa request_human_attestation
    al crear la petición. Lo firmado (msg EXEMPTION_SLOT:hash) y lo comparado
    (content_sha256) es ese hash semántico, no el crudo: evita mismatch semántico/crudo.
    Reusa ccdd.valid_signers (misma mecánica que R6 para slots críticos estáticos)."""
    import semantic_hash
    h = semantic_hash.get_semantic_hash(code_str, ext)
    base = contract_dir or (Path(__file__).resolve().parent.parent / "contracts" / "complexity-agent")
    attest = _load_json(base / "attestations.json") or {}
    registry = _load_json(base / "reviewers.json")
    if not registry:
        return False, h  # sin registro de revisores no hay firma verificable
    exceptions = attest.get("complexity_exception", [])
    if isinstance(exceptions, dict):
        exceptions = [exceptions]
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import ccdd  # noqa: E402  (lib upstream; reusa sign/verify Ed25519 de R6)
    signers = ccdd.valid_signers(exceptions, registry, EXEMPTION_SLOT, h)
    return bool(signers), h


def _report_findings(path, det):
    """Imprime el veredicto y devuelve el código de salida (0 PASS / 2 FAIL)."""
    crit = [f for f in det.get("findings", []) if f.get("severity") == "CRÍTICA"]
    high = [f for f in det.get("findings", []) if f.get("severity") == "ALTA"]
    if not crit:
        if high:
            print(f"[complexity-gate] PASS con avisos ALTA en {os.path.basename(path)} "
                  f"({len(high)}). Revisar, no bloquea.", file=sys.stderr)
        return 0
    lines = [f"  • {f['function']}: {f['metric']} = {f['value']} (CRÍTICA)" for f in crit]
    print("[complexity-gate] FAIL en " + os.path.basename(path) +
          " — gate determinista (umbrales firmados). Refactoriza antes de continuar:\n" +
          "\n".join(lines) +
          "\nSugerencia: aplanar anidamiento (guard clauses). Si esto es una exigencia "
          "estricta de negocio, usa la tool 'request_human_attestation'.",
          file=sys.stderr)
    return 2


def main():
    path = target_path()
    if not path or not os.path.exists(path):
        return 0  # no-op: sin ruta o no existe
    backend = resolve_backend(path)
    if backend is None:
        return 0  # no-op anunciado: extensión sin backend
    code_str = Path(path).read_text(encoding="utf-8")
    ext = Path(path).suffix or ".py"

    exempt, h = _is_exempt(code_str, ext)
    if exempt:
        print(f"[complexity-gate] PASS en {os.path.basename(path)} "
              f"(EXCEPCIÓN FIRMADA para hash {h[:8]}).", file=sys.stderr)
        return 0

    det = backend.extract_source(code_str, os.path.basename(path))
    return _report_findings(path, det)


if __name__ == "__main__":
    sys.exit(main())
