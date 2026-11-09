"""Información para revisar un período; no cierra ni modifica sus datos."""
from django.db.models import Count, Sum

from sgr.models import AporteIndicador, AsignacionMeta, Meta


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
