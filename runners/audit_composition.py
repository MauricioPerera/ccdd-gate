#!/usr/bin/env python3
"""audit_composition.py — destaca COMPOSICIÓN SIN GATEAR. Determinista, sin LLM.

Encuentra funciones (contratos kind:function) cuyo target IMPORTA el módulo de otro target del
proyecto —o sea, participa en un ensamblaje— pero NO está dentro de ningún contrato kind:group.
Esas aristas de composición quedan sin árbitro: cada función pasa su gate aislada, pero el ENSAMBLE
(donde viven los bugs de integración) no lo verifica nadie.

Es un SURFACER, no un candado: ningún harness impide a un agente con acceso a disco escribir código,
pero esto vuelve la deuda de verificación VISIBLE y AUDITABLE. Pensado para CI: exit 1 si hay
composición sin gatear, así "verificar el ensamble" deja de ser opcional.

Uso:  python audit_composition.py [raiz]
Salida: JSON {functions, groups, ungated_composition:[...], ok}. Exit 0 si ok, 1 si hay deuda."""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_lint  # noqa: E402


def _contracts(root):
    out = []
    for p in Path(root).rglob("*.md"):
        try:
            fm, _ = tc_lint.split_front_matter(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if fm and "task" in fm:
            out.append((p, fm))
    return out


def _imported_stems(pyfile):
    """Conjunto de nombres importados por un .py (último componente de cada módulo + nombres
    traídos por `from x import y`). Determinista vía AST; '' si no parsea."""
    try:
        tree = ast.parse(Path(pyfile).read_text(encoding="utf-8"))
    except Exception:
        return set()
    stems = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                stems.add(a.name.split(".")[-1])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                stems.add(n.module.split(".")[-1])
            for a in n.names:
                stems.add(a.name)
    return stems


def _rel(path, rootp):
    """Ruta relativa a la raíz (no expone la estructura del runner). Absoluta si no es relativa."""
    try:
        return str(path.relative_to(rootp))
    except ValueError:
        return str(path)


_MOCK_HINTS = ("unittest.mock", "from mock", "import mock", "MagicMock", "patch(", "monkeypatch", "Mock(")


def _test_verifies(test):
    """True si el test del composer EXISTE y NO mockea: entonces ejercita los hijos reales y la
    composición está verificada por el gate de la función (deuda de forma, no de comportamiento)."""
    if not test or not test.exists():
        return False
    try:
        src = test.read_text(encoding="utf-8")
    except Exception:
        return False
    return not any(h in src for h in _MOCK_HINTS)


def audit(root):
    """Devuelve {functions, groups, ungated_composition, behavior_unverified, ok}. Lista las
    funciones que importan a otro target sin un kind:group; `behavior_verified` por arista distingue
    deuda de FORMA (el test del composer ejercita los hijos reales) de deuda de COMPORTAMIENTO (el
    test mockea o falta -> el ensamble NO se verifica). `ok` = sin deuda de comportamiento. Rutas
    relativas a `root`."""
    rootp = Path(root).resolve()
    funcs = {}        # stem -> (cpath, target, test)
    grouped = set()
    groups = 0
    for p, fm in _contracts(root):
        if fm.get("kind") == "group":
            groups += 1
            grouped.update((p.parent / ch).resolve() for ch in (fm.get("children") or []))
        elif "target" in fm:
            test = (p.parent / fm["tests"]) if fm.get("tests") else None
            funcs[Path(fm["target"]).stem] = (p.resolve(), p.parent / fm["target"], test)
    uncovered = []
    for stem, (cpath, tgt, test) in sorted(funcs.items()):
        if not tgt.exists():
            continue
        # _imported_stems(tgt) re-leía y re-parseaba el target O(N) veces por stem (una por `s` en
        # el `in` de la comprensión) -> O(N²) parses. Hoist fuera de la comprensión: se lee/parsea
        # UNA vez por stem. Resultado idéntico (la función es pura en el contenido del target).
        stems = _imported_stems(tgt)
        composes = sorted(s for s in funcs if s != stem and s in stems)
        if composes and cpath not in grouped:
            uncovered.append({"contract": _rel(cpath, rootp), "composes": composes,
                              "behavior_verified": _test_verifies(test)})
    behavior_debt = [u for u in uncovered if not u["behavior_verified"]]
    return {"functions": len(funcs), "groups": groups, "ungated_composition": uncovered,
            "behavior_unverified": behavior_debt, "ok": not behavior_debt}


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    res = audit(root)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
