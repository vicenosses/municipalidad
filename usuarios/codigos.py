import secrets

from django.db import IntegrityError, transaction


def guardar_con_codigo_automatico(instancia, prefijo, guardar):
    with transaction.atomic():
        instancia.codigo = f'AUTO-{secrets.token_hex(12)}'
        guardar()

        numero = instancia.pk
        while True:
            codigo = f'{prefijo}-{numero:03d}'
            if instancia.__class__._default_manager.filter(
                codigo=codigo
            ).exclude(pk=instancia.pk).exists():
                numero += 1
                continue

            instancia.codigo = codigo
            try:
                with transaction.atomic():
                    guardar(update_fields=['codigo'], force_insert=False)
                return instancia
            except IntegrityError:
                if not instancia.__class__._default_manager.filter(
                    codigo=codigo
                ).exclude(pk=instancia.pk).exists():
                    raise
                numero += 1
