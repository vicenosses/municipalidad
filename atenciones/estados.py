"""Registro explícito de creación y transiciones autorizadas de Actividad."""
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from atenciones.permisos import puede_cambiar_estado, queryset_atenciones
from auditoria.utils import registrar_auditoria
from sgr.aportes import reiniciar_por_reapertura


@transaction.atomic
def registrar_creacion_actividad(actividad, actor):
    """Solo tras crear una Actividad nueva; no reconstruye datos anteriores."""
    actual = AtencionCiudadana.objects.select_for_update().get(pk=actividad.pk)
    evento, _ = HistorialEstadoActividad.objects.get_or_create(
        actividad=actual, estado_anterior='',
        defaults={'estado_nuevo': actual.estado, 'actor': actor, 'fecha_hora': actual.fecha_registro},
    )
    return evento


@transaction.atomic
def cambiar_estado_actividad(request, actividad_pk, nuevo_estado, motivo=''):
    actividad = get_object_or_404(queryset_atenciones(request).select_for_update(), pk=actividad_pk)
    if not puede_cambiar_estado(request, actividad, nuevo_estado):
        raise Http404
    anterior = actividad.estado
    etiqueta_anterior = actividad.get_estado_display()
    actividad.estado = nuevo_estado
    actividad.save(update_fields=['estado'])
    HistorialEstadoActividad.objects.create(
        actividad=actividad, estado_anterior=anterior, estado_nuevo=nuevo_estado,
        actor=request.user, fecha_hora=timezone.now(), motivo=motivo.strip(),
    )
    if anterior == AtencionCiudadana.Estado.CERRADA and nuevo_estado == AtencionCiudadana.Estado.EN_PROCESO:
        reiniciar_por_reapertura(request, actividad)
    registrar_auditoria(request, 'cambiar_estado', actividad,
        f'Estado de actividad: {etiqueta_anterior} → {actividad.get_estado_display()}')
    return actividad
