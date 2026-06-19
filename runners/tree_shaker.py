import ast
import re
from pathlib import Path

class DependencyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.dependencies = set()

    def visit_Name(self, node):
        self.dependencies.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        self.dependencies.add(node.attr)
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.dependencies.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.dependencies.add(node.module.split('.')[0])
        for alias in node.names:
            self.dependencies.add(alias.name)
        self.generic_visit(node)

def extract_dependencies(target_path: str) -> set[str]:
    """Extrae todos los nombres (variables, clases, funciones, imports) usados en el AST del archivo target."""
    path = Path(target_path)
    if not path.exists() or path.suffix != ".py":
        return set()
    
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        visitor = DependencyVisitor()
        visitor.visit(tree)
        # Limpiar palabras muy comunes o cortas para evitar falsos positivos masivos
        # (ej. len, list, str, i, j)
        return {d for d in visitor.dependencies if len(d) > 2}
    except Exception:
        return set()

def shake(slot_text: str, target_path: str, max_chars: int = None) -> str:
    """
    Comprime un texto dinámico reteniendo solo los bloques que mencionan dependencias del target_path.
    Si max_chars se especifica y el resultado lo excede, aplica un truncate final bruto.
    (usamos max_chars como proxy rápido de max_tokens, asumiendo ~4 chars/token).
    """
    deps = extract_dependencies(target_path)
    if not deps:
        # Si no pudimos extraer dependencias (ej. archivo no existe), fallamos graceful truncando
        return slot_text[:max_chars] if max_chars else slot_text

    patterns = _compile_dep_patterns(deps)
    # Separar en bloques (ej. definiciones de clases/funciones) y retener los que mencionan deps
    kept_blocks = [block for block in re.split(r'\n\s*\n', slot_text)
                   if block.strip() and _block_mentions_dep(block, patterns)]

    shaked_text = "\n\n".join(kept_blocks)
    # Si especificamos un tamaño y aún nos pasamos, aplicamos un truncate clásico al final
    if max_chars and len(shaked_text) > max_chars:
        return shaked_text[:max_chars]
    return shaked_text


def _compile_dep_patterns(deps, chunk_size=100):
    """Regex por chunks (palabra completa) para las dependencias: r'\\b(?:Name1|Name2)\\b'.
    Se divide en chunks para no romper el motor de regex cuando hay muchas deps."""
    escaped = [re.escape(d) for d in deps]
    return [re.compile(r'\b(?:' + '|'.join(escaped[i:i + chunk_size]) + r')\b')
            for i in range(0, len(escaped), chunk_size)]


def _block_mentions_dep(block, patterns):
    return any(p.search(block) for p in patterns)
