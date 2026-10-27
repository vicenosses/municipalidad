from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa, filtrar_contexto_territorial, en_contexto_delegacion


def registros_cargables(request, modelo):
    if modelo is AtencionCiudadana:
        qs = modelo.objects.filter(
            activo=True,
        ).exclude(estado=AtencionCiudadana.Estado.CERRADA)
    elif modelo is Compromiso:
        qs = modelo.objects.all()
    else:
        return modelo.objects.none()

    rol = obtener_rol(request.user)
    qs = filtrar_contexto_territorial(qs, request)
    if rol == 'administrador':
        return qs

    delegacion = get_delegacion_activa(request)
    if delegacion is None:
        return qs.none()
    qs = qs.filter(delegacion=delegacion)
    if rol == 'delegado':
        return qs
    if rol in ('coordinador', 'funcionario', 'verificador'):
        return qs.filter(responsable=request.user)
    return qs.none()


def _registro_padre(evidencia):
    if evidencia.atencion_id:
        return evidencia.atencion
    if evidencia.compromiso_id:
        return evidencia.compromiso
    return None


def _en_delegacion_activa(request, registro):
    return (
        registro is not None
        and get_delegacion_activa(request) == registro.delegacion
    )


def puede_agregar_evidencia(request, registro):
    if registro is None:
        return False
    return registros_cargables(request, type(registro)).filter(pk=registro.pk).exists()


def puede_validar_evidencia(request, evidencia):
    if evidencia.estado != evidencia.Estado.PENDIENTE:
        return False
    rol = obtener_rol(request.user)
    registro = _registro_padre(evidencia)
    if registro is None or not en_contexto_delegacion(request, registro.delegacion):
        return False
    if rol in ('administrador', 'verificador') and registro.creado_por_id == request.user.pk:
        return False
    if rol == 'administrador':
        return True
    if (
        rol == 'verificador'
        and registro is not None
        and registro.creado_por_id == request.user.pk
    ):
        return False
    return (
        rol in ('delegado', 'verificador')
        and _en_delegacion_activa(request, registro)
    )
