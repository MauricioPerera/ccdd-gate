"""Módulo de ejemplo con complejidad estructural alta, para el análisis post-código.
Contiene una función con ciclomática elevada, anidamiento profundo y demasiados parámetros,
además de una segunda función con lógica condicional densa. Sirve de fixture determinista."""


def procesar_pedido(cliente, lineas, direccion, metodo_pago, cupon, almacen, canal, urgente, reintentos):
    total = 0
    for linea in lineas:
        if linea["cantidad"] > 0:
            if linea["precio"] > 0:
                if cliente["tipo"] == "mayorista":
                    if linea["cantidad"] > 100:
                        if cupon and cupon["valido"]:
                            total += linea["precio"] * linea["cantidad"] * 0.7
                        else:
                            total += linea["precio"] * linea["cantidad"] * 0.8
                    else:
                        total += linea["precio"] * linea["cantidad"] * 0.9
                elif cliente["tipo"] == "vip":
                    if cupon:
                        total += linea["precio"] * linea["cantidad"] * 0.85
                    else:
                        total += linea["precio"] * linea["cantidad"]
                else:
                    total += linea["precio"] * linea["cantidad"]
            elif linea["precio"] == 0 and urgente:
                total += 0
            else:
                raise ValueError("precio invalido")
        elif linea["cantidad"] == 0:
            continue
        else:
            raise ValueError("cantidad invalida")
    if metodo_pago == "tarjeta" and total > 1000 or metodo_pago == "transferencia" and urgente:
        total *= 1.02
    if almacen is None and canal == "web":
        almacen = "central"
    while reintentos > 0 and total < 0:
        reintentos -= 1
    return total


def clasificar_riesgo(monto, historial, region, edad_cuenta, flag_manual):
    if monto > 10000:
        if region in ("alto_riesgo", "sancionada"):
            return "bloquear"
        elif historial == "moroso" or edad_cuenta < 30:
            return "revision_manual"
        else:
            return "revision_automatica"
    elif monto > 1000:
        if flag_manual:
            return "revision_manual"
        elif historial == "moroso":
            return "revision_automatica"
        else:
            return "aprobar"
    else:
        return "aprobar"
