from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class UsernameOrEmailBackend(ModelBackend):
    """Permite autenticación con nombre de usuario o correo."""

    def user_can_authenticate(self, user):
        if not super().user_can_authenticate(user):
            return False
        perfil = getattr(user, 'perfil', None)
        return perfil is None or perfil.activo

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            user = User.objects.filter(email__iexact=username).exclude(email='').first()
        if user is None:
            return None
        if not user.check_password(password):
            return None
        if not self.user_can_authenticate(user):
            return None
        return user
