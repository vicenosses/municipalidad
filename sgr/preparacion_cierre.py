"""Diagnóstico de preparación: no cierra ni modifica datos del período."""
from django.db.models import Count, Sum
from django.utils import timezone

from sgr.asignaciones import calcular_resultado_con_cantidad
from sgr.models import AporteIndicador, AsignacionMeta, Meta


def diagnosticar_periodo(periodo):
    metas = Meta.objects.filter(periodo=periodo, activo=True)
    asignaciones = AsignacionMeta.objects.filter(
        meta__periodo=periodo, meta__activo=True, activa=True,
    ).select_related('meta__delegacion', 'funcionario').order_by(
        'funcionario__username', 'meta__nombre', 'pk')
    pendientes = AporteIndicador.objects.filter(
        indicador__meta__periodo=periodo,
        estado__in=(AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.REQUIERE_CORRECCION),
    ).select_related('actividad', 'indicador__meta__delegacion').order_by('actividad__fecha', 'pk')
    sin_asignacion = metas.exclude(pk__in=asignaciones.values('meta_id')).select_related('delegacion')
    funcionarios = list(asignaciones.values(
        'funcionario_id', 'funcionario__username', 'funcionario__first_name', 'funcionario__last_name',
    ).annotate(cantidad=Count('id'), ponderacion=Sum('ponderacion')).order_by('funcionario__username'))
    conteos = AporteIndicador.objects.filter(
        indicador__meta__periodo=periodo,
        actividad__fecha__range=(periodo.fecha_inicio, periodo.fecha_fin),
        estado=AporteIndicador.Estado.CUMPLE,
    ).values('indicador__meta_id', 'actividad__responsable_id').annotate(total=Count('pk'))
    cantidades = {(fila['indicador__meta_id'], fila['actividad__responsable_id']): fila['total'] for fila in conteos}
    resultados = []
    asignaciones_invalidas = 0
    for asignacion in asignaciones:
        if not asignacion.cantidad_objetivo or asignacion.cantidad_objetivo <= 0:
            asignaciones_invalidas += 1
            continue
        cantidad = cantidades.get((asignacion.meta_id, asignacion.funcionario_id), 0)
        resultados.append(calcular_resultado_con_cantidad(asignacion, cantidad))
    return {
        'metas_activas': metas.count(), 'metas_sin_asignacion': sin_asignacion.count(),
        'lista_metas_sin_asignacion': sin_asignacion.order_by('nombre', 'pk')[:25],
        'asignaciones': asignaciones.count(), 'asignaciones_invalidas': asignaciones_invalidas,
        'pendientes': pendientes.count(), 'lista_pendientes': pendientes[:25],
        'funcionarios': funcionarios, 'resultados': resultados,
        'periodo_terminado': periodo.fecha_fin < timezone.localdate(),
    }
