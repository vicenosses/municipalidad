from django.core.exceptions import ValidationError


class ComplejidadContrasenaValidator:
    def validate(self, password, user=None):
        errores = []
        if not any(c.isupper() for c in password):
            errores.append('La contraseña debe incluir al menos una letra mayúscula.')
        if not any(c.isdigit() for c in password):
            errores.append('La contraseña debe incluir al menos un número.')
        if not any(not c.isalnum() and not c.isspace() for c in password):
            errores.append('La contraseña debe incluir al menos un carácter especial, como !, @ o #.')
        if errores:
            raise ValidationError(errores, code='password_sin_complejidad')

    def get_help_text(self):
        return 'Debe incluir al menos una letra mayúscula, un número y un carácter especial (por ejemplo, !, @ o #).'
