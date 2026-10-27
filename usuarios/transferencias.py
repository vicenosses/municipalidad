from django.core.exceptions import ValidationError
from django.db import transaction

from usuarios.models import Delegacion, Perfil


class CompromisosPendientesError(ValidationError):
    def __init__(self, cantidad):
        self.cantidad = cantidad
        super().__init__(
            f'El usuario tiene {cantidad} compromiso(s) activo(s); confirme '
            'explícitamente la transferencia para continuar.'
        )


def contar_compromisos_activos(usuario):
    from agenda.models import Compromiso

    return Compromiso.objects.filter(responsable=usuario).exclude(
        estado=Compromiso.Estado.REALIZADO
    ).count()


@transaction.atomic
def aplicar_transferencia(usuario, delegacion_origen, delegacion_destino, confirmar_compromisos):
    perfil = (
        Perfil.objects.select_for_update()
        .select_related('delegacion')
        .get(usuario=usuario)
    )
    if perfil.delegacion_id != delegacion_origen.pk:
        raise ValidationError('El usuario ya no pertenece a la delegación de origen.')
    if not perfil.delegaciones.filter(pk=delegacion_origen.pk).exists():
        raise ValidationError('El usuario no está autorizado en la delegación de origen.')
    if (
        delegacion_destino.pk == delegacion_origen.pk
        or not Delegacion.objects.filter(pk=delegacion_destino.pk, activa=True).exists()
    ):
        raise ValidationError('Seleccione una delegación de destino activa y distinta.')

    compromisos = contar_compromisos_activos(usuario)
    if compromisos and not confirmar_compromisos:
        raise CompromisosPendientesError(compromisos)

    perfil.delegacion = delegacion_destino
    perfil.save(update_fields=['delegacion'])
    perfil.delegaciones.remove(delegacion_origen)
    perfil.delegaciones.add(delegacion_destino)
    return compromisos
