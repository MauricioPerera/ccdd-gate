import ast
import hashlib

def get_semantic_hash(content: str, extension: str) -> str:
    """
    Calcula un hash semántico (ignorando comentarios y espacios en blanco)
    si la extensión corresponde a un lenguaje soportado (actualmente .py).
    Hace un fallback a SHA-256 crudo en caso de error de sintaxis o para otros archivos.
    """
    if extension == ".py":
        try:
            tree = ast.parse(content)
            # dump serializa el árbol. En Python >= 3.9 include_attributes es False por defecto
            # por lo que no incluye números de línea.
            dump_str = ast.dump(tree)
            return hashlib.sha256(dump_str.encode("utf-8")).hexdigest()
        except Exception:
            # Fallback seguro (ej. syntax error en un archivo temporal o tests rotos)
            pass

    # Fallback genérico para texto u otros lenguajes
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
