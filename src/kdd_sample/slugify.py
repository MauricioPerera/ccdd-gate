"""slugify — ejemplo KDD (OKF + CCDD). Función pura, stdlib, chiquita.

Implementación del task-contract knowledge/contracts/kdd-sample-slugify.md.
Convierte un str arbitrario en un slug ASCII seguro para URLs.
"""


def slugify(text: str) -> str:
    out = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum() and ch.isascii():
            out.append(ch)
            prev_dash = False
            continue
        if not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")