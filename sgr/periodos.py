from datetime import datetime

from django.core.exceptions import ValidationError
from django.utils import timezone


def periodo_cerrado_para_fecha(fecha):
    if fecha is None:
        return False
    if isinstance(fecha, datetime):
        fecha = timezone.localtime(fecha).date() if timezone.is_aware(fecha) else fecha.date()
    from sgr.models import Periodo

    return Periodo.objects.filter(
        cerrado=True,
        fecha_inicio__lte=fecha,
        fecha_fin__gte=fecha,
    ).exists()


def validar_periodo_abierto(fecha, mensaje):
    if periodo_cerrado_para_fecha(fecha):
        raise ValidationError(mensaje)
