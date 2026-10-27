from datetime import timedelta

from django.utils import timezone


def limite_asociacion(fecha):
    """Tres días lunes-viernes posteriores a la fecha de la Actividad."""
    limite = fecha
    restantes = 3
    while restantes:
        limite += timedelta(days=1)
        if limite.weekday() < 5:
            restantes -= 1
    return limite


def dentro_plazo(fecha, hoy=None):
    hoy = hoy or timezone.localdate()
    return fecha <= hoy <= limite_asociacion(fecha)
