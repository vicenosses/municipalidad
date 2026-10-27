from django.db.models import Q

from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa


def delegacion_catalogo(request):
    if request is None:
        return None
    return get_delegacion_activa(request)


def es_administrador_catalogos(request):
    return request is None or obtener_rol(request.user) == 'administrador'


def catalogos_visibles(queryset, request):
    if request is None or (es_administrador_catalogos(request) and delegacion_catalogo(request) is None):
        return queryset
    delegacion = delegacion_catalogo(request)
    if delegacion is None:
        return queryset.filter(es_general=True, delegacion__isnull=True)
    return queryset.filter(
        Q(es_general=True, delegacion__isnull=True)
        | Q(es_general=False, delegacion=delegacion)
    )


def catalogos_editables(queryset, request):
    if request is None or (es_administrador_catalogos(request) and delegacion_catalogo(request) is None):
        return queryset
    delegacion = delegacion_catalogo(request)
    if delegacion is None:
        return queryset.none()
    return queryset.filter(es_general=False, delegacion=delegacion)
