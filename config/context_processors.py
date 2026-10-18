from usuarios.mixins import obtener_nombre_rol, obtener_permisos
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa


def sesion_sgr(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    return {
        'sesion_delegacion': get_delegacion_activa(request),
        'sesion_rol': obtener_nombre_rol(request.user),
        'sesion_nombre': request.user.get_full_name() or request.user.username,
        'sesion_delegaciones': delegaciones_autorizadas(request.user),
        'sesion_permisos': obtener_permisos(request.user),
    }
