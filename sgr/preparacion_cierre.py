"""Información para revisar un período; no cierra ni modifica sus datos."""
from django.db.models import Count, Sum
from django.utils import timezone

from sgr.asignaciones import calcular_resultado_asignacion
from sgr.models import AporteIndicador, AsignacionMeta, Meta
from sgr.ponderaciones import calcular_resultados_metas


def diagnosticar_periodo(periodo):
    metas = Meta.objects.filter(periodo=periodo, activo=True)
    asignaciones = AsignacionMeta.objects.filter(meta__periodo=periodo, meta__activo=True, activa=True)
    pendientes = AporteIndicador.objects.filter(
        indicador__meta__periodo=periodo,
        estado__in=(AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.REQUIERE_CORRECCION),
    )
    funcionarios = list(asignaciones.values(
        'funcionario_id', 'funcionario__username', 'funcionario__first_name', 'funcionario__last_name',
    ).annotate(cantidad=Count('id'), ponderacion=Sum('ponderacion')).order_by('funcionario__username'))
    return {'metas_activas': metas.count(),
            'metas_sin_asignacion': metas.exclude(pk__in=asignaciones.values('meta_id')).count(),
            'asignaciones': asignaciones.count(), 'pendientes': pendientes.count(),
            'funcionarios': funcionarios}


def crear_snapshot_cierre(periodo):
    """Captura en JSON los resultados vigentes antes de inmovilizar el período."""
    metas = list(
        Meta.objects.filter(periodo=periodo, activo=True)
        .select_related('delegacion')
        .prefetch_related('indicadores')
    )
    resultados = calcular_resultados_metas(metas)
    metas_snapshot = []
    for meta in metas:
        resultado = resultados[meta.pk]
        metas_snapshot.append({
            'id': meta.pk,
            'nombre': meta.nombre,
            'delegacion': str(meta.delegacion),
            'cumplimiento_normalizado': (
                str(resultado.cumplimiento_normalizado)
                if resultado.cumplimiento_normalizado is not None else None
            ),
            'resultado_ponderado_bruto': (
                str(resultado.resultado_ponderado_bruto)
                if resultado.resultado_ponderado_bruto is not None else None
            ),
            'cobertura_calculable': str(resultado.cobertura_calculable),
            'ponderacion_asignada': str(resultado.ponderacion_asignada),
            'indicadores': [{
                'id': fila.indicador.pk,
                'nombre': fila.indicador.nombre,
                'activo': fila.indicador.activo,
                'ponderacion': str(fila.ponderacion) if fila.ponderacion is not None else None,
                'cumplimiento': (
                    str(fila.metrica.cumplimiento.porcentaje)
                    if fila.metrica.cumplimiento.porcentaje is not None else None
                ),
                'resultado_ponderado': (
                    str(fila.resultado_ponderado)
                    if fila.resultado_ponderado is not None else None
                ),
                'estado': fila.estado,
            } for fila in resultado.indicadores],
        })

    asignaciones = []
    for asignacion in AsignacionMeta.objects.filter(
        meta__periodo=periodo, activa=True,
    ).select_related('meta', 'funcionario'):
        resultado = calcular_resultado_asignacion(asignacion)
        asignaciones.append({
            'id': asignacion.pk,
            'meta_id': asignacion.meta_id,
            'meta': asignacion.meta.nombre,
            'funcionario_id': asignacion.funcionario_id,
            'funcionario': asignacion.funcionario.get_username(),
            'cantidad_objetivo': str(asignacion.cantidad_objetivo),
            'ponderacion': str(asignacion.ponderacion),
            'actividades_aprobadas_ponderadas': resultado.cantidad,
            'cumplimiento': str(resultado.cumplimiento_aplicable),
            'resultado_ponderado': str(resultado.resultado_ponderado),
        })

    estados_aportes = dict(AporteIndicador.objects.filter(
        indicador__meta__periodo=periodo,
    ).values_list('estado').annotate(cantidad=Count('pk')))
    return {
        'version': 1,
        'capturado_en': timezone.now().isoformat(),
        'periodo': {
            'id': periodo.pk,
            'nombre': periodo.nombre,
            'fecha_inicio': periodo.fecha_inicio.isoformat(),
            'fecha_fin': periodo.fecha_fin.isoformat(),
        },
        'metas': metas_snapshot,
        'asignaciones': asignaciones,
        'aportes_por_estado': estados_aportes,
    }
