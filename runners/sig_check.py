"""sig_check.py — conformidad de la firma IMPLEMENTADA vs la del contrato. STUB: lo implementa el
modelo pequeño (glm) bajo el CCDD gate. No editar a mano (el experimento mide al implementador)."""
import ast


def _param_names(args):
    """Nombres ORDENADOS y marcados de los params: posonly, pos, *vararg, kwonly, **kwarg."""
    names = [a.arg for a in args.posonlyargs]
    names += [a.arg for a in args.args]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names += [a.arg for a in args.kwonlyargs]
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


def _find_function(tree, fn_name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return node
    return None


def _parse_signature(signature):
    src = signature.strip().rstrip(":")
    fn = ast.parse(src + ":\n    pass").body[0]
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise ValueError("no es un def")
    return fn


def signature_mismatch(source: str, fn_name: str, expected_signature: str) -> str:
    try:
        impl_tree = ast.parse(source)
        expected_fn = _parse_signature(expected_signature)
    except (SyntaxError, ValueError):
        return "parse error"
    impl_fn = _find_function(impl_tree, fn_name)
    if impl_fn is None:
        return "function not found: " + fn_name
    impl_params = _param_names(impl_fn.args)
    expected_params = _param_names(expected_fn.args)
    if impl_params != expected_params:
        return "param mismatch: " + str(impl_params) + " != " + str(expected_params)
    return ""