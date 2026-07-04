#!/usr/bin/env python3
"""linter_gate.py — envuelve LINTERS EXTERNOS deterministas como checks opt-in del gate.

Hermano idiomatico de rules_gate.py: misma idea declarativa (entradas = {tool, glob, ...}) y
mismo arbitro INSOBORNABLE, pero el veredicto lo emite un linter externo (ruff, ...) invocado
como subproceso con salida machine-readable, NO un LLM. Cierra el hueco opuesto al de
rules_gate: este no reimplementa reglas en AST, delega en la herramienta pinneada y solo
normaliza su salida a findings.

DETERMINISMO PRIMERO: la salida de un linter depende de su version, por eso `version` es
OBLIGATORIO en cada entrada (pin exacto). Version instalada != pin -> exit 2 (entorno invalido,
NO es PASS). Tool no instalada: required:false -> skip anunciado por stderr + exit 0
(precedente tree-sitter del repo); required:true -> exit 2. Findings -> exit 1. Limpio -> exit 0.

Arquitectura extensible: registro ADAPTERS por nombre de tool. Cada adaptador sabe
(a) leer su version instalada, (b) invocar con salida machine-readable, (c) normalizar.
HOY solo ruff; el registro queda listo para clippy/eslint/golangci-lint sin implementarlos.

Config (YAML): lista de entradas { tool, version, files?, args?, required? }.
Uso:  python linter_gate.py [linters.yaml] [root]
Exit: 0 limpio · 1 findings · 2 config/entorno invalido. Sin LLM."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class ToolError(Exception):
    """Fallo del linter externo (crash, JSON inválido, etc.) -> entorno invalido (exit 2)."""


def _real_runner(args, cwd):
    """subprocess wrapper inyectable: (args_list, cwd) -> (returncode, stdout, stderr).

    Sin shell=True, encoding utf-8. cwd=None usa el directorio actual (para `tool --version`).
    Los tests inyectan un fake runner para las politicas (version mismatch, ausente, required).
    """
    import subprocess
    proc = subprocess.run(args, cwd=cwd, capture_output=True, encoding="utf-8")
    return proc.returncode, proc.stdout, proc.stderr


class RuffAdapter:
    """Adaptador ruff: `ruff check --output-format json` normalizado a findings."""
    name = "ruff"

    def installed_version(self, runner):
        """String de version instalada, o None si ruff no esta instalada (FileNotFoundError)."""
        try:
            rc, out, _ = runner([self.name, "--version"], None)
        except FileNotFoundError:
            return None
        if rc != 0:
            return None
        # salida: "ruff 0.15.20"
        parts = out.strip().split()
        return parts[1] if len(parts) >= 2 else out.strip()

    def collect(self, files, args, root, runner):
        """Invoca ruff sobre `files` (paths relativos a root) y normaliza a findings ordenados."""
        cmd = [self.name, "check", "--output-format", "json"] + list(args or []) + list(files)
        rc, out, err = runner(cmd, root)
        if rc not in (0, 1):  # 0 limpio · 1 findings · otro = crash/error -> entorno invalido
            raise ToolError(f"ruff falló (exit {rc}): {err.strip() or out.strip()}")
        try:
            data = json.loads(out) if out.strip() else []
        except json.JSONDecodeError as e:
            raise ToolError(f"ruff devolvió JSON inválido: {e}")
        return self._normalize(data, root)

    def _normalize(self, data, root):
        """[{file (relativo, /), line, code, msg}] ordenado deterministicamente por (file, line, code)."""
        rootp = Path(root).resolve()
        findings = []
        for d in data:
            fn = d.get("filename", "") or ""
            loc = d.get("location") or {}
            line = loc.get("row") or 0
            code = d.get("code") or ""
            msg = d.get("message") or ""
            try:  # ruff siempre reporta filename absoluto -> relativizar al root
                rel = Path(fn).resolve().relative_to(rootp).as_posix()
            except (ValueError, OSError):
                rel = Path(fn).as_posix()
            findings.append({"file": rel, "line": line, "code": code, "msg": msg})
        findings.sort(key=lambda f: (f["file"], f["line"], f["code"]))
        return findings


# Registro de adaptadores por nombre de tool. Hoy solo ruff; clippy/eslint/golangci-lint
# se registran aqui (misma interfaz: installed_version/collect) cuando se implementen.
ADAPTERS = {"ruff": RuffAdapter()}


def _load_linters(path):
    """Lista de entradas validadas, o (None, error). `version` (pin exacto) es obligatorio."""
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return None, "linters debe ser una lista de entradas {tool, version, ...}"
    entries = []
    for e in data:
        if not isinstance(e, dict) or "tool" not in e or "version" not in e:
            return None, f"entrada inválida (faltan tool/version): {e}"
        if e["tool"] not in ADAPTERS:
            return None, f"tool desconocida '{e['tool']}'; válidas: {sorted(ADAPTERS)}"
        if not isinstance(e["version"], str) or not e["version"].strip():
            return None, f"version inválida (debe ser string pin exacto): {e}"
        entries.append({
            "tool": e["tool"],
            "version": e["version"],
            "files": e.get("files", "**/*.py"),
            "args": list(e.get("args", [])),
            "required": bool(e.get("required", False)),
        })
    return entries, None


def gate(config_path, root=".", runner=None):
    """(exit_code, payload). runner inyectable para tests (default: subprocess real).

    exit 0 limpio · 1 findings · 2 config/entorno invalido. payload JSON:
    {ok, results:[{tool, version, skipped?, findings}]} (en invalido, {ok:false, error, results}).
    """
    if runner is None:
        runner = _real_runner
    entries, err = _load_linters(config_path)
    if err:
        return 2, {"ok": False, "error": err, "results": []}
    rootp = Path(root)
    results = []
    any_findings = False
    for e in entries:
        adapter = ADAPTERS[e["tool"]]
        inst = adapter.installed_version(runner)
        if inst is None:  # no instalada
            if e["required"]:
                return 2, {"ok": False,
                           "error": f"{e['tool']} no instalada pero required:true (pin {e['version']})",
                           "results": results}
            print(f"[linter-gate] skip: {e['tool']} no instalada (required:false, pin {e['version']})",
                  file=sys.stderr)
            results.append({"tool": e["tool"], "version": e["version"], "skipped": True,
                            "reason": "not installed", "findings": []})
            continue
        if inst != e["version"]:  # entorno invalido: determinismo primero
            return 2, {"ok": False,
                       "error": f"entorno inválido: {e['tool']} instalada {inst} != pin {e['version']}",
                       "results": results}
        files = [f.relative_to(rootp).as_posix()
                 for f in sorted(rootp.glob(e["files"])) if f.is_file()]
        if not files:  # glob vacio: nada que lintear -> limpio (ruff sin args escanearia `.`)
            results.append({"tool": e["tool"], "version": e["version"], "findings": []})
            continue
        try:
            findings = adapter.collect(files, e["args"], str(rootp), runner)
        except ToolError as te:
            return 2, {"ok": False, "error": str(te), "results": results}
        results.append({"tool": e["tool"], "version": e["version"], "findings": findings})
        if findings:
            any_findings = True
    return (1 if any_findings else 0), {"ok": not any_findings, "results": results}


def main(argv=None):
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    argv = argv if argv is not None else sys.argv[1:]
    config_path = argv[0] if len(argv) > 0 else "linters.yaml"
    root = argv[1] if len(argv) > 1 else "."
    code, payload = gate(config_path, root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())