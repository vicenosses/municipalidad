import re

from django.db.models import Q

from auditoria.models import RegistroAuditoria
from auditoria.permisos import ids_texto
from auditoria.presentacion import presentar_registros
from sgr.models import AporteIndicador


def historial_actividad(actividad):
    """Solo se invoca después de autorizar el detalle de la actividad."""
    directos = Q(modelo=actividad._meta.label, objeto_id=str(actividad.pk))
    evidencias = Q(
        modelo='evidencias.Evidencia',
        objeto_id__in=ids_texto(actividad.evidencias.filter(compromiso__isnull=True)),
    )
    # Excepción limitada al formato emitido por CompromisoDesdeActividadView.
    # La M2M por sí sola no demuestra desde qué actividad se creó el compromiso.
    candidatos = RegistroAuditoria.objects.filter(
        modelo='agenda.Compromiso', accion='crear_compromiso_desde_actividad',
        objeto_id__in=ids_texto(actividad.compromisos.filter(delegacion=actividad.delegacion)),
    )
    origen = re.compile(r'\ACompromiso [^\r\n]*? creado desde la actividad ([0-9]+): ')
    ids_agenda = []
    for registro in candidatos:
        if registro.descripcion.count(' creado desde la actividad ') != 1:
            continue
        coincidencia = origen.match(registro.descripcion)
        if coincidencia and coincidencia[1] == str(actividad.pk):
            ids_agenda.append(registro.pk)
    registros = RegistroAuditoria.objects.filter(
        directos | evidencias | Q(pk__in=ids_agenda) | Q(
            modelo='sgr.AporteIndicador', objeto_id__in=ids_texto(AporteIndicador.objects.filter(actividad=actividad))
        )
    ).select_related('usuario').order_by('-timestamp', '-pk')
    return presentar_registros(list(registros))
