from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from usuarios.models import permisos_por_codigo


def obtener_rol(user):
    """Devuelve el código de rol del perfil o administrador si es superusuario."""
    if not user.is_authenticated or not user.is_active:
        return None
    perfil = getattr(user, 'perfil', None)
    if perfil is not None and not perfil.activo:
        return None
    if user.is_superuser:
        return 'administrador'
    if perfil and perfil.activo and user.is_active and perfil.rol_id and perfil.rol.activo:
        return perfil.rol_codigo
    return None


def obtener_permisos(user):
    codigo = obtener_rol(user)
    if not codigo:
        return {}
    base = permisos_por_codigo(codigo)
    if user.is_superuser:
        return {clave: True for clave in base}
    perfil = getattr(user, 'perfil', None)
    if perfil and isinstance(perfil.rol.permisos, dict) and perfil.rol.permisos:
        combinado = dict(base)
        combinado.update(perfil.rol.permisos)
        return combinado
    return base


def obtener_nombre_rol(user):
    codigo = obtener_rol(user)
    if not codigo:
        return '—'
    if user.is_superuser:
        return 'Administrador'
    perfil = getattr(user, 'perfil', None)
    if perfil and perfil.rol_id:
        return perfil.rol.nombre
    return codigo.title()


class RolRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe la vista a uno o más códigos de rol."""

    roles_permitidos = ()
    raise_exception = True

    def test_func(self):
        rol = obtener_rol(self.request.user)
        return rol in self.roles_permitidos
