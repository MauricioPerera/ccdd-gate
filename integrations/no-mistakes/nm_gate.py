#!/usr/bin/env python3
"""nm_gate.py — check DETERMINISTA de ccdd-gate para usar como `commands.test` de no-mistakes.

no-mistakes (https://github.com/kunchenguid/no-mistakes) corre `commands.test` como paso
determinista del pipeline; si sale ≠0 escala. Este wrapper corre los chequeos project-wide de
ccdd-gate SIN LLM (complejidad vía repo_gate + anotaciones + composición) y devuelve UN exit code.

Conéctalo en `.no-mistakes.yaml` (ver no-mistakes.yaml.example) con `auto_fix.test: 0` para que un
fallo ESCALE al humano/glm en vez de que el agente de no-mistakes lo autofixee — así se preserva el
veredicto determinista de ccdd-gate (su razón de ser) dentro del pipeline de entrega de no-mistakes.

Uso:  python integrations/no-mistakes/nm_gate.py [root]
Exit: 0 todos los checks verdes · 1 algún check falló."""
import subprocess
import sys
from pathlib import Path

RUNNERS = Path(__file__).resolve().parents[2] / "runners"
sys.path.insert(0, str(RUNNERS))


def _repo_gate(root):
    """Complejidad sobre el código de producción (repo_gate, exit-coded). True si pasa."""
    r = subprocess.run([sys.executable, str(RUNNERS / "repo_gate.py")],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or r.stderr).strip())
    return r.returncode == 0


def main():
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    import audit_annotations
    import audit_composition

    results = {"complexity": _repo_gate(root)}
    aa = audit_annotations.audit(root)
    results["annotations"] = bool(aa.get("ok"))
    print(f"[nm-gate] annotations ok={results['annotations']} failures={aa.get('failures')}")
    ac = audit_composition.audit(root)
    results["composition"] = bool(ac.get("ok"))
    print(f"[nm-gate] composition ok={results['composition']} behavior_unverified={ac.get('behavior_unverified')}")

    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print(f"[nm-gate] FAIL — checks en rojo: {failed}")
        return 1
    print("[nm-gate] PASS — todos los checks deterministas de ccdd-gate en verde")
    return 0


if __name__ == "__main__":
    sys.exit(main())
