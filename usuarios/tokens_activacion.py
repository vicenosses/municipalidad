from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class TokenActivacion(PasswordResetTokenGenerator):
    """Usa el mismo formato seguro de Django con vigencia propia de diez minutos."""

    vigencia_segundos = 10 * 60

    def check_token(self, user, token):
        if not user or not token:
            return False
        try:
            timestamp, _ = token.split('-')
            timestamp = base36_to_int(timestamp)
        except (ValueError, TypeError):
            return False
        valido = any(constant_time_compare(self._make_token_with_timestamp(user, timestamp, secret), token)
                     for secret in [self.secret, *self.secret_fallbacks])
        edad = self._num_seconds(self._now()) - timestamp
        return valido and 0 <= edad <= self.vigencia_segundos


token_activacion = TokenActivacion()
