"""Duración de ejecución desde transiciones estructuradas, sin inferir fechas."""
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from atenciones.models import AtencionCiudadana

MICROSEGUNDOS_HORA = Decimal('3600000000')
MICROSEGUNDOS_DIA = Decimal('86400000000')


def microsegundos_transcurridos(inicio, fin):
    diferencia = fin.astimezone(UTC) - inicio.astimezone(UTC)
    return (diferencia.days * 86400 + diferencia.seconds) * 1000000 + diferencia.microseconds


def microsegundos_habiles(inicio, fin):
    """Tiempo real dentro de lunes-viernes; un día equivale a 24 horas."""
    zona = timezone.get_default_timezone()
    cursor = inicio.astimezone(UTC)
    final = fin.astimezone(UTC)
    total = 0
    while cursor < final:
        fecha_local = cursor.astimezone(zona).date()
        siguiente = datetime.combine(fecha_local + timedelta(days=1), time.min, tzinfo=zona).astimezone(UTC)
        limite = min(siguiente, final)
        if fecha_local.weekday() < 5:
            total += microsegundos_transcurridos(cursor, limite)
        cursor = limite
    return total


@dataclass(frozen=True)
class DuracionActividad:
    valor: Decimal | None
    ciclos_completos: int
    motivo_no_calculable: str = ''


def calcular_duracion_actividad(actividad, historial, *, dias_habiles=False):
    """Exige una secuencia fiable sin ciclos faltantes o abiertos.

    Un primer evento Registrada → En proceso basta aunque falte la creación.
    Una secuencia que empieza cerrada/reabierta pierde ciclos anteriores y no
    permite conocer la duración total de ejecución de esa Actividad.
    """
    eventos = list(historial)
    if not eventos:
        return DuracionActividad(None, 0, 'sin_historial')
    estado = None
    ultimo_instante = None
    inicio = None
    ciclos = 0
    total = 0
    estados = AtencionCiudadana.Estado
    transiciones = {(estados.REGISTRADA, estados.EN_PROCESO),
                    (estados.EN_PROCESO, estados.CERRADA), (estados.CERRADA, estados.EN_PROCESO)}
    for posicion, evento in enumerate(eventos):
        instante = evento.fecha_hora
        if timezone.is_naive(instante):
            return DuracionActividad(None, ciclos, 'historial_inconsistente')
        instante = instante.astimezone(UTC)
        if ultimo_instante is not None and instante < ultimo_instante:
            return DuracionActividad(None, ciclos, 'historial_inconsistente')
        ultimo_instante = instante
        anterior, nuevo = evento.estado_anterior, evento.estado_nuevo
        if posicion == 0:
            if anterior == '' and nuevo in (estados.REGISTRADA, estados.EN_PROCESO):
                estado = nuevo
                inicio = instante if nuevo == estados.EN_PROCESO else None
                continue
            if (anterior, nuevo) != (estados.REGISTRADA, estados.EN_PROCESO):
                return DuracionActividad(None, ciclos, 'historial_incompleto')
            estado = anterior
        if anterior != estado or (anterior, nuevo) not in transiciones:
            return DuracionActividad(None, ciclos, 'historial_inconsistente')
        if nuevo == estados.EN_PROCESO:
            inicio = instante
        elif nuevo == estados.CERRADA:
            if inicio is None:
                return DuracionActividad(None, ciclos, 'historial_incompleto')
            total += (microsegundos_habiles(inicio, instante) if dias_habiles
                      else microsegundos_transcurridos(inicio, instante))
            ciclos += 1
            inicio = None
        estado = nuevo
    if inicio is not None or ciclos == 0:
        return DuracionActividad(None, ciclos, 'historial_incompleto')
    if estado != actividad.estado:
        return DuracionActividad(None, ciclos, 'historial_inconsistente')
    divisor = MICROSEGUNDOS_DIA if dias_habiles else MICROSEGUNDOS_HORA
    return DuracionActividad(Decimal(total) / divisor, ciclos)
