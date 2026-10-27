from sgr.permisos import ROLES_INFORMES
from usuarios.mixins import obtener_nombre_rol, obtener_permisos, obtener_rol
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa


def sesion_sgr(request):
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    rol = obtener_rol(request.user)
    delegacion = get_delegacion_activa(request)
    return {
        'sesion_delegacion': delegacion,
        'sesion_contexto': ('Global: todas las delegaciones' if rol == 'administrador' and delegacion is None
                           else delegacion),
        'sesion_selector_delegacion': rol == 'administrador',
        'sesion_contexto_recuperado': getattr(request, 'contexto_territorial_recuperado', False),
        'sesion_rol': obtener_nombre_rol(request.user),
        'sesion_nombre': request.user.get_full_name() or request.user.username,
        'sesion_delegaciones': delegaciones_autorizadas(request.user),
        'sesion_permisos': obtener_permisos(request.user),
        'sesion_rol_codigo': rol,
        'sesion_auditoria': rol in ('administrador', 'delegado', 'coordinador'),
        'sesion_sgr_periodos': rol in ('administrador', 'delegado', 'coordinador'),
        'sesion_informes_sgr': rol in ROLES_INFORMES,
        'sesion_validar_aportes': rol in ('administrador', 'delegado', 'verificador'),
        'sesion_catalogos': rol in ('administrador', 'coordinador', 'delegado'),
        'sesion_catalogo_completo': rol in ('administrador', 'coordinador'),
    }
