from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogos.models import SolicitudCatalogoGeneral, SubAtencion, TipoAtencion


class ConflictoSolicitudCatalogo(ValidationError):
    pass


@transaction.atomic
def aprobar_solicitud(solicitud, administrador):
    solicitud = SolicitudCatalogoGeneral.objects.select_for_update().get(
        pk=solicitud.pk
    )
    if solicitud.estado != SolicitudCatalogoGeneral.Estado.PENDIENTE:
        raise ConflictoSolicitudCatalogo('La solicitud ya fue resuelta.')

    modelo = (
        TipoAtencion
        if solicitud.tipo_solicitud == SolicitudCatalogoGeneral.Tipo.CATEGORIA
        else SubAtencion
    )
    if solicitud.tipo_solicitud == SolicitudCatalogoGeneral.Tipo.CATEGORIA:
        duplicado = modelo.objects.filter(codigo=solicitud.codigo).exists()
        duplicado = duplicado or modelo.objects.filter(
            es_general=True,
            nombre__iexact=solicitud.nombre,
        ).exists()
    else:
        duplicado = False
        padre = solicitud.categoria_padre
        if not padre.activo or not padre.es_general or padre.delegacion_id is not None:
            raise ConflictoSolicitudCatalogo(
                'La categoría padre ya no está disponible como categoría general.'
            )
        duplicado = duplicado or modelo.objects.filter(
            tipo=padre,
            es_general=True,
            nombre__iexact=solicitud.nombre,
        ).exists()
    if duplicado:
        raise ConflictoSolicitudCatalogo(
            'Existe un catálogo con el mismo código o nombre general.'
        )

    try:
        if solicitud.tipo_solicitud == SolicitudCatalogoGeneral.Tipo.CATEGORIA:
            catalogo = TipoAtencion(
                codigo=solicitud.codigo,
                nombre=solicitud.nombre,
                descripcion=solicitud.descripcion,
                activo=True,
                es_general=True,
                delegacion=None,
            )
        else:
            catalogo = SubAtencion(
                nombre=solicitud.nombre,
                tipo=solicitud.categoria_padre,
                activo=True,
                es_general=True,
                delegacion=None,
            )
        catalogo.save()
    except (IntegrityError, ValidationError) as error:
        raise ConflictoSolicitudCatalogo(
            'No se pudo crear el catálogo por un conflicto de integridad.'
        ) from error

    solicitud.estado = SolicitudCatalogoGeneral.Estado.APROBADA
    solicitud.decidido_por = administrador
    solicitud.fecha_decision = timezone.now()
    solicitud.save(
        update_fields=['estado', 'decidido_por', 'fecha_decision']
    )
    return catalogo


@transaction.atomic
def rechazar_solicitud(solicitud, administrador, motivo=''):
    solicitud = SolicitudCatalogoGeneral.objects.select_for_update().get(
        pk=solicitud.pk
    )
    if solicitud.estado != SolicitudCatalogoGeneral.Estado.PENDIENTE:
        raise ConflictoSolicitudCatalogo('La solicitud ya fue resuelta.')
    solicitud.estado = SolicitudCatalogoGeneral.Estado.RECHAZADA
    solicitud.decidido_por = administrador
    solicitud.fecha_decision = timezone.now()
    solicitud.motivo_decision = motivo
    solicitud.save(
        update_fields=[
            'estado',
            'decidido_por',
            'fecha_decision',
            'motivo_decision',
        ]
    )
    return solicitud
