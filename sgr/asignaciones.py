"""Cálculo individual basado en aportes revisados del período correspondiente."""
from dataclasses import dataclass
from decimal import Decimal

from sgr.models import AporteIndicador


@dataclass(frozen=True)
class ResultadoAsignacion:
    asignacion: object
    cantidad: int
    cumplimiento: Decimal
    cumplimiento_aplicable: Decimal
    resultado_ponderado: Decimal


def aportes_asignacion(asignacion):
    return AporteIndicador.objects.filter(
        indicador__meta=asignacion.meta,
        actividad__responsable=asignacion.funcionario,
        actividad__fecha__range=(asignacion.meta.periodo.fecha_inicio, asignacion.meta.periodo.fecha_fin),
        estado=AporteIndicador.Estado.CUMPLE,
    ).select_related('actividad', 'indicador').order_by('-actividad__fecha', '-pk')


def calcular_resultado_asignacion(asignacion):
    cantidad = aportes_asignacion(asignacion).count()
    cumplimiento = Decimal(cantidad) / asignacion.cantidad_objetivo * Decimal('100')
    aplicable = min(cumplimiento, Decimal('120'))
    return ResultadoAsignacion(asignacion, cantidad, cumplimiento, aplicable,
                               aplicable * asignacion.ponderacion / Decimal('100'))
