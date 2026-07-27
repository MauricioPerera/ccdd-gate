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
HOY ruff, clippy, govet y sqlfluff; el registro queda listo para eslint/golangci-lint sin implementarlos.

Config (YAML): lista de entradas { tool, version, files?, args?, required? }.
Uso:  python linter_gate.py [linters.yaml] [root]
Exit: 0 limpio · 1 findings · 2 config/entorno invalido. Sin LLM."""
import json
import re
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
    default_files = "**/*.py"

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


class ClippyAdapter:
    """Adaptador clippy: `cargo clippy --message-format=json` normalizado a findings.

    A diferencia de ruff (linter por-archivo), clippy linta el crate/workspace COMPLETO desde
    `root` -- no acepta una lista de archivos como input. `files` (el glob de la entrada YAML)
    se usa solo para dos cosas: (1) decidir si hay algo que lintear (glob vacio -> skip sin
    invocar clippy, mismo contrato que ruff) y (2) post-filtrar los findings a esos paths tras
    normalizarlos, para que un `files: "crates/topcoat-core/**/*.rs"` no reporte lints de otros
    crates del mismo workspace.
    """
    name = "clippy"
    default_files = "**/*.rs"

    def installed_version(self, runner):
        """String de version instalada, o None si clippy no esta (FileNotFoundError)."""
        try:
            rc, out, _ = runner(["cargo", "clippy", "--version"], None)
        except FileNotFoundError:
            return None
        if rc != 0:
            return None
        # salida: "clippy 0.1.96 (ac68faa20c 2026-05-25)"
        parts = out.strip().split()
        return parts[1] if len(parts) >= 2 else out.strip()

    def collect(self, files, args, root, runner):
        """Invoca `cargo clippy` una vez sobre TODO `root` y filtra a `files`, normalizado."""
        cmd = ["cargo", "clippy", "--message-format=json"] + list(args or [])
        rc, out, err = runner(cmd, root)
        # 0 limpio (o con warnings sin -D warnings) · 101 clippy deniega (-D warnings) o error de
        # compilacion (ese error TAMBIEN es un finding, no un crash) · otro = entorno invalido.
        if rc not in (0, 101):
            raise ToolError(f"cargo clippy falló (exit {rc}): {err.strip() or out.strip()}")
        diagnostics = self._parse_messages(out)
        allowed = {f.replace("\\", "/") for f in files}
        return self._normalize(diagnostics, root, allowed)

    def _parse_messages(self, out):
        """Diagnosticos de nivel warning/error de la salida JSON-lines de cargo. Nunca lanza por
        una linea no-JSON o sin 'code' (mensajes de resumen del propio cargo, sin lint asociado)."""
        out_msgs = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("reason") != "compiler-message":
                continue
            msg = data.get("message") or {}
            if msg.get("level") not in ("warning", "error"):
                continue
            if not (msg.get("code") or {}).get("code"):
                continue  # sin codigo de lint = resumen ("N warnings emitted"), no un finding
            out_msgs.append(msg)
        return out_msgs

    def _normalize(self, diagnostics, root, allowed):
        """[{file (relativo, /), line, code, msg}] ordenado, filtrado a `allowed` si no vacio."""
        findings = []
        for msg in diagnostics:
            spans = msg.get("spans") or []
            primary = next((s for s in spans if s.get("is_primary")), spans[0] if spans else None)
            raw_file = (primary or {}).get("file_name", "")
            rel = raw_file.replace("\\", "/")
            if allowed and rel not in allowed:
                continue
            findings.append({
                "file": rel,
                "line": (primary or {}).get("line_start") or 0,
                "code": (msg.get("code") or {}).get("code") or "",
                "msg": msg.get("message") or "",
            })
        findings.sort(key=lambda f: (f["file"], f["line"], f["code"]))
        return findings


# Una linea de `go vet` hallazgo: `<ruta-relativa>:<linea>:<columna>: <mensaje>`. La ruta puede
# venir con backslash en Windows (ej. `pkgb\pkgb.go`) -- se normaliza a forward-slash. En Go < 1.25
# la ruta trae prefijo `./` (Linux) / `.\` (Windows): `./main.go:6:2:`. Como el glob de `files` da
# paths relativos SIN prefijo (ej. `main.go`), hay que strippear ese `./` o el finding se filtraria
# contra `allowed` y se perderia (gate devolveria code 0 pese a haber hallazgo). Lineas que no
# matchean (encabezados `# example.com/probe`, etc.) se ignoran silenciosamente.
GOVET_LINE_RE = re.compile(r"^(.+?):(\d+):(\d+):\s*(.+)$")


class GoVetAdapter:
    """Adaptador go vet: `go vet` normalizado a findings.

    Como clippy (no como ruff), `go vet` linta el MODULO/PAQUETE COMPLETO desde `root` -- no
    acepta archivos sueltos como input. `files` (el glob de la entrada YAML) se usa solo para
    dos cosas: (1) decidir si hay algo que lintear (glob vacio -> skip sin invocar go vet, mismo
    contrato que ruff/clippy) y (2) post-filtrar los findings a esos paths tras normalizarlos.

    Salida verificada de `go vet ./...` (cwd=root): exit 0 limpio sin output; exit 1 con un
    hallazgo POR LINEA en STDERR (no stdout) con formato `<ruta-relativa>:<linea>:<col>: <msg>`.
    `go vet` no tiene codigos de regla por hallazgo (a diferencia de ruff F401 o clippy::foo), por
    eso el campo `code` de cada finding es la constante "govet". Version via `go version` (no
    existe `go vet --version`): 3er token = "go1.26.4" (prefijo "go" incluido, igual que el pin).
    """
    name = "go"  # binario invocado; registrado en ADAPTERS bajo la clave "govet"
    default_files = "**/*.go"

    def installed_version(self, runner):
        """String de version instalada (ej. "go1.26.4"), o None si go no esta (FileNotFoundError)."""
        try:
            rc, out, _ = runner([self.name, "version"], None)
        except FileNotFoundError:
            return None
        if rc != 0:
            return None
        # salida: "go version go1.26.4 windows/amd64" -> 3er token = "go1.26.4"
        parts = out.strip().split()
        return parts[2] if len(parts) >= 3 else out.strip()

    def collect(self, files, args, root, runner):
        """Invoca `go vet` una vez sobre TODO `root` (default `./...` si args vacio) y filtra a
        `files`, normalizado. exit 0 limpio · 1 findings · otro = entorno invalido (ToolError)."""
        cmd = [self.name, "vet"] + (list(args) if args else ["./..."])
        rc, out, err = runner(cmd, root)
        if rc not in (0, 1):  # 0 limpio · 1 findings · otro = crash/entorno invalido
            raise ToolError(f"go vet falló (exit {rc}): {(err or '').strip() or (out or '').strip()}")
        messages = self._parse_messages(err)
        allowed = {f.replace("\\", "/") for f in files}
        return self._normalize(messages, root, allowed)

    def _parse_messages(self, out):
        """Findings crudos de `go vet` desde stderr: lista de {file, line, col, msg} (file ya con
        forward-slash y sin prefijo `./`). Lineas que no matchean GOVET_LINE_RE se ignoran
        silenciosamente; nunca lanza."""
        out_msgs = []
        for line in (out or "").splitlines():
            m = GOVET_LINE_RE.match(line)
            if not m:
                continue
            rel = m.group(1).replace("\\", "/")
            if rel.startswith("./"):  # Go < 1.25 prefija `./`; el glob de `files` no lo trae
                rel = rel[2:]
            out_msgs.append({
                "file": rel,
                "line": int(m.group(2)),
                "col": int(m.group(3)),
                "msg": m.group(4),
            })
        return out_msgs

    def _normalize(self, messages, root, allowed):
        """[{file (relativo, /), line, code:"govet", msg}] ordenado por (file, line, code), filtrado
        a `allowed` si no vacio. `root` se conserva por simetria con ClippyAdapter (paths de go vet
        ya son relativos al cwd, no hace falta relativizar)."""
        findings = []
        for m in messages:
            rel = m["file"]
            if allowed and rel not in allowed:
                continue
            findings.append({"file": rel, "line": m["line"], "code": "govet", "msg": m["msg"]})
        findings.sort(key=lambda f: (f["file"], f["line"], f["code"]))
        return findings


class SqlfluffAdapter:
    """Adaptador sqlfluff: `sqlfluff lint --format json` normalizado a findings.

    Por-archivo como ruff (NO de modulo completo como clippy/govet): acepta una LISTA de archivos
    como argumentos posicionales al final y puede lintear varios en una sola invocacion. El
    dialecto SQL (postgres, ansi, mysql, ...) se pasa via `--dialect <nombre>` como parte de `args`
    en la config YAML -- no se hardcodea aca; es responsabilidad de quien escribe el linters.yaml
    declarar el dialecto de su proyecto.

    Salida verificada de `sqlfluff lint <args> <files...> --format json` (v4.2.2): exit 0 limpio ·
    1 con violaciones · otro = crash/entorno invalido. A diferencia de ruff (array plano de
    findings individuales ya con su filename), sqlfluff anida: la salida es una LISTA con un item
    POR ARCHIVO `{filepath, violations:[...]}`, y los hallazgos van DENTRO de cada archivo. Cada
    violation tiene su propio `code` de regla (ej. LT09, LT01) -- a diferencia de go vet. Version
    via `sqlfluff --version`: "sqlfluff, version 4.2.2" -> ultimo token = "4.2.2" (3 tokens con una
    coma pegada al primero; NO usar parts[1] como hace RuffAdapter).
    """
    name = "sqlfluff"
    default_files = "**/*.sql"

    def installed_version(self, runner):
        """String de version instalada, o None si sqlfluff no esta (FileNotFoundError)."""
        try:
            rc, out, _ = runner([self.name, "--version"], None)
        except FileNotFoundError:
            return None
        if rc != 0:
            return None
        # salida: "sqlfluff, version 4.2.2" -> ultimo token = "4.2.2"
        parts = out.strip().split()
        return parts[-1] if parts else out.strip()

    def collect(self, files, args, root, runner):
        """Invoca sqlfluff sobre `files` (paths relativos a root) y normaliza a findings ordenados."""
        cmd = [self.name, "lint"] + list(args or []) + list(files) + ["--format", "json"]
        rc, out, err = runner(cmd, root)
        if rc not in (0, 1):  # 0 limpio · 1 findings · otro = crash/error -> entorno invalido
            raise ToolError(f"sqlfluff falló (exit {rc}): {err.strip() or out.strip()}")
        try:
            data = json.loads(out) if out.strip() else []
        except json.JSONDecodeError as e:
            raise ToolError(f"sqlfluff devolvió JSON inválido: {e}")
        return self._normalize(data, root)

    def _normalize(self, data, root):
        """[{file (relativo, /), line, code, msg}] ordenado deterministicamente por (file, line, code).

        Itera la lista externa (un item por archivo, `filepath` = path -- suele ser relativo al
        cwd, pero se normaliza defensivamente relativizando a `root` con fallback igual que
        RuffAdapter) y por cada archivo itera su lista interna `violations` extrayendo
        `start_line_no`/`code`/`description`. Archivos con `violations: []` no generan findings.
        """
        rootp = Path(root).resolve()
        findings = []
        for fobj in data or []:
            fn = fobj.get("filepath", "") or ""
            try:
                rel = Path(fn).resolve().relative_to(rootp).as_posix()
            except (ValueError, OSError):
                rel = Path(fn).as_posix()
            for v in fobj.get("violations") or []:
                findings.append({
                    "file": rel,
                    "line": v.get("start_line_no") or 0,
                    "code": v.get("code") or "",
                    "msg": v.get("description") or "",
                })
        findings.sort(key=lambda f: (f["file"], f["line"], f["code"]))
        return findings


# Registro de adaptadores por nombre de tool. Hoy ruff, clippy, govet y sqlfluff; eslint/golangci-lint
# se registran aqui (misma interfaz: installed_version/collect) cuando se implementen.
ADAPTERS = {"ruff": RuffAdapter(), "clippy": ClippyAdapter(), "govet": GoVetAdapter(),
            "sqlfluff": SqlfluffAdapter()}


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
            "files": e.get("files", ADAPTERS[e["tool"]].default_files),
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