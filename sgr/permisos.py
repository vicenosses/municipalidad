from sgr.models import Indicador, Meta
from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa, filtrar_contexto_territorial

ROLES_METAS = ('administrador', 'delegado', 'coordinador')
ROLES_ESTADO_META = ('administrador', 'delegado')
ROLES_INFORMES = (*ROLES_METAS, 'funcionario', 'verificador')


def metas_visibles(request):
    qs = Meta.objects.select_related('periodo', 'delegacion', 'creado_por')
    rol = obtener_rol(request.user)
    if rol not in ROLES_METAS:
        return qs.none()
    return filtrar_contexto_territorial(qs, request)


def puede_crear_meta(request):
    rol = obtener_rol(request.user)
    return rol == 'administrador' or (
        rol in ROLES_METAS and get_delegacion_activa(request) is not None
    )


def indicadores_visibles(request):
    return Indicador.objects.filter(meta__in=metas_visibles(request)).select_related(
        'meta__periodo', 'meta__delegacion', 'creado_por',
    )


def indicador_modificable(indicador):
    return indicador.meta.activo and indicador.meta.periodo.activo
