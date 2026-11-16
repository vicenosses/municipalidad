"""Reglas de seguimiento de las gestiones sociales."""


def falta_plazo_para_tubo(ingresa_al_tubo, fecha_compromiso, anterior=None):
    """Mantiene editables los registros antiguos que ya estaban sin plazo."""
    if not ingresa_al_tubo or fecha_compromiso:
        return False
    anterior = anterior or {}
    return not (anterior.get('ingresa_al_tubo') and anterior.get('fecha_compromiso') is None)
