from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from usuarios.models import IntentosIngreso

MAX_INTENTOS = 5
DURACION = timedelta(minutes=15)


def clave_identificador(valor):
    from django.contrib.auth.models import User
    identificador = (valor or '').strip()[:254]
    usuario = User.objects.filter(username__iexact=identificador).first()
    if usuario is None:
        usuario = User.objects.filter(email__iexact=identificador).exclude(email='').first()
    clave = f'usuario:{usuario.pk}' if usuario else f'desconocido:{identificador.casefold()}'
    return salted_hmac('sgr.intentos_ingreso', clave, algorithm='sha256').hexdigest()


def esta_bloqueado(valor):
    registro = IntentosIngreso.objects.filter(identificador_hash=clave_identificador(valor)).first()
    return bool(registro and registro.bloqueado_hasta and registro.bloqueado_hasta > timezone.now())


@transaction.atomic
def registrar_fallo(valor):
    clave = clave_identificador(valor)
    registro, _ = IntentosIngreso.objects.get_or_create(identificador_hash=clave)
    registro = IntentosIngreso.objects.select_for_update().get(pk=registro.pk)
    ahora = timezone.now()
    if registro.bloqueado_hasta and registro.bloqueado_hasta <= ahora:
        registro.intentos = 0
        registro.bloqueado_hasta = None
    if not registro.bloqueado_hasta:
        registro.intentos += 1
        if registro.intentos >= MAX_INTENTOS:
            registro.bloqueado_hasta = ahora + DURACION
    registro.save(update_fields=['intentos', 'bloqueado_hasta', 'actualizado'])


def limpiar_intentos(valor):
    IntentosIngreso.objects.filter(identificador_hash=clave_identificador(valor)).delete()
