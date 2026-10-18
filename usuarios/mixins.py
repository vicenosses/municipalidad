from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from usuarios.models import permisos_por_codigo


def obtener_rol(user):
    """Devuelve el código de rol del perfil o administrador si es superusuario."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'administrador'
    perfil = getattr(user, 'perfil', None)
    if perfil and perfil.activo and user.is_active:
        return perfil.rol_codigo
    return None


def obtener_permisos(user):
    codigo = obtener_rol(user)
    base = permisos_por_codigo(codigo) if codigo else {}
    if user.is_superuser:
        return {clave: True for clave in base}
    perfil = getattr(user, 'perfil', None)
    if perfil and perfil.rol_id and isinstance(perfil.rol.permisos, dict) and perfil.rol.permisos:
        combinado = dict(base)
        combinado.update(perfil.rol.permisos)
        return combinado
    return base


def obtener_nombre_rol(user):
    if user.is_superuser:
        return 'Administrador'
    perfil = getattr(user, 'perfil', None)
    if perfil and perfil.rol_id:
        return perfil.rol.nombre
    codigo = obtener_rol(user)
    return codigo.title() if codigo else '—'


class RolRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe la vista a uno o más códigos de rol."""

    roles_permitidos = ()
    raise_exception = True

    def test_func(self):
        rol = obtener_rol(self.request.user)
        return rol in self.roles_permitidos
