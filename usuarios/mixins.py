from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


def obtener_rol(user):
    """Devuelve el rol del perfil o administrador si es superusuario."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return 'administrador'
    perfil = getattr(user, 'perfil', None)
    if perfil and perfil.activo:
        return perfil.rol
    return None


class RolRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restringe la vista a uno o más roles institucionales."""

    roles_permitidos = ()

    def test_func(self):
        rol = obtener_rol(self.request.user)
        return rol in self.roles_permitidos
