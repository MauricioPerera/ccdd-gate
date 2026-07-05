"""slugify — ejemplo KDD (OKF + CCDD). Función pura, stdlib, chiquita.

Implementación del task-contract knowledge/contracts/kdd-sample-slugify.md.
Convierte un str arbitrario en un slug ASCII seguro para URLs.
"""


def slugify(text: str) -> str:
    out = ["-"]
    for ch in text.lower():
        if ch.isalnum() and ch.isascii():
            out.append(ch)
            continue
        if out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")