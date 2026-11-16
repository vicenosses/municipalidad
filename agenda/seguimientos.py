"""Reglas compartidas para guardar seguimiento de compromisos."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404

from agenda.models import Compromiso, HistorialCompromiso
from auditoria.utils import registrar_auditoria
from usuarios.sesion import en_contexto_delegacion


@transaction.atomic
def registrar_seguimiento(request, compromiso_id, tipo, descripcion):
    from agenda.views import puede_editar_compromiso
    compromiso = get_object_or_404(Compromiso.objects.select_for_update(), pk=compromiso_id)
    if (not en_contexto_delegacion(request, compromiso.delegacion)
            or not puede_editar_compromiso(request.user, compromiso)
            or compromiso.estado == Compromiso.Estado.REALIZADO):
        raise PermissionDenied('No puede registrar seguimiento en este compromiso.')
    evento = HistorialCompromiso.objects.create(compromiso=compromiso, campo=tipo,
        valor_nuevo=descripcion, realizado_por=request.user)
    registrar_auditoria(request, 'agregar_seguimiento_compromiso', compromiso,
                        f'Seguimiento {evento.pk} registrado para {compromiso.codigo}.')
    return evento
