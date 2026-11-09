import re

from django.core.exceptions import ValidationError


def validar_y_formatear_rut(valor):
    valor = (valor or '').strip().upper()
    if not valor:
        return ''
    if not re.fullmatch(r'[0-9.\-K\s]+', valor):
        raise ValidationError('Ingrese un RUT válido.')
    rut = re.sub(r'[.\-\s]', '', valor)
    if not re.fullmatch(r'\d{7,8}[0-9K]', rut):
        raise ValidationError('Ingrese un RUT válido con dígito verificador.')
    numero, digito = rut[:-1], rut[-1]
    total = sum(int(n) * (2 + i % 6) for i, n in enumerate(reversed(numero)))
    resto = 11 - total % 11
    esperado = '0' if resto == 11 else 'K' if resto == 10 else str(resto)
    if digito != esperado:
        raise ValidationError('El dígito verificador del RUT no es válido.')
    return f'{int(numero):,}'.replace(',', '.') + '-' + digito
