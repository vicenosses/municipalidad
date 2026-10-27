"""Reglas existentes de alcance y transición, compartidas con el servicio."""
from atenciones.models import AtencionCiudadana
from usuarios.mixins import obtener_rol
from usuarios.sesion import en_contexto_delegacion, filtrar_contexto_territorial

ROLES_GESTORES_ESTADO = ('administrador', 'delegado', 'coordinador')
ROLES_OPERATIVOS_ESTADO = ('funcionario', 'verificador')


def puede_cambiar_estado(request, atencion, nuevo_estado):
    if not atencion.activo:
        return False
    rol = obtener_rol(request.user)
    if rol not in (*ROLES_GESTORES_ESTADO, *ROLES_OPERATIVOS_ESTADO):
        return False
    dentro_del_alcance = en_contexto_delegacion(request, atencion.delegacion)
    if not dentro_del_alcance:
        return False
    if rol in ROLES_OPERATIVOS_ESTADO and atencion.creado_por_id != request.user.pk:
        return False
    transiciones = {
        AtencionCiudadana.Estado.REGISTRADA: {AtencionCiudadana.Estado.EN_PROCESO},
        AtencionCiudadana.Estado.EN_PROCESO: {AtencionCiudadana.Estado.CERRADA},
        AtencionCiudadana.Estado.CERRADA: (
            {AtencionCiudadana.Estado.EN_PROCESO} if rol in ROLES_GESTORES_ESTADO else set()
        ),
    }
    return nuevo_estado in transiciones.get(atencion.estado, set())


def queryset_atenciones(request):
    qs = AtencionCiudadana.objects.select_related('tipo', 'subatencion', 'delegacion', 'responsable')
    return filtrar_contexto_territorial(qs, request)
