"""Alcance territorial conservador, sin inferencias desde texto libre."""
from django.db.models import CharField, F, Q
from django.db.models.functions import Cast
from django.contrib.auth import get_user_model

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import SolicitudCatalogoGeneral, SubAtencion, TipoAtencion
from evidencias.models import Evidencia
from sgr.models import AporteIndicador, Indicador, Meta
from usuarios.mixins import obtener_rol
from usuarios.models import Perfil, SolicitudTransferencia
from usuarios.sesion import get_delegacion_activa


def ids_texto(queryset):
    # Comparar texto con texto evita conversiones numéricas implícitas en MariaDB.
    return queryset.order_by().annotate(
        auditoria_id=Cast('pk', output_field=CharField())
    ).values('auditoria_id')


def registros_autorizados(request, queryset):
    rol = obtener_rol(request.user)
    if rol not in ('administrador', 'delegado', 'coordinador'):
        return queryset.none()
    delegacion = get_delegacion_activa(request)
    if rol == 'administrador' and delegacion is None:
        return queryset
    if delegacion is None:
        return queryset.none()

    evidencias = Evidencia.objects.filter(
        Q(atencion__delegacion=delegacion, compromiso__isnull=True)
        | Q(compromiso__delegacion=delegacion, atencion__isnull=True)
    )
    origenes = (
        (AporteIndicador, AporteIndicador.objects.filter(
            actividad__delegacion=delegacion, indicador__meta__delegacion=delegacion,
            actividad__fecha__gte=F('indicador__meta__periodo__fecha_inicio'),
            actividad__fecha__lte=F('indicador__meta__periodo__fecha_fin'),
        )),
        (Indicador, Indicador.objects.filter(meta__delegacion=delegacion)),
        (Meta, Meta.objects.filter(delegacion=delegacion)),
        (AtencionCiudadana, AtencionCiudadana.objects.filter(delegacion=delegacion)),
        (Compromiso, Compromiso.objects.filter(delegacion=delegacion)),
        (Evidencia, evidencias),
        (TipoAtencion, TipoAtencion.objects.filter(delegacion=delegacion, es_general=False)),
        (SubAtencion, SubAtencion.objects.filter(delegacion=delegacion, es_general=False)),
        (SolicitudCatalogoGeneral, SolicitudCatalogoGeneral.objects.filter(
            delegacion_solicitante=delegacion)),
        (SolicitudTransferencia, SolicitudTransferencia.objects.filter(
            delegacion_origen=delegacion)),
    )
    permitido = Q(pk__in=[])
    for modelo, objetos in origenes:
        permitido |= Q(modelo=modelo._meta.label, objeto_id__in=ids_texto(objetos))
    if rol == 'administrador':
        perfiles = Perfil.objects.filter(delegaciones=delegacion)
        for modelo, objetos in ((Perfil, perfiles), (get_user_model(), get_user_model().objects.filter(
            perfil__in=perfiles))):
            permitido |= Q(modelo=modelo._meta.label, objeto_id__in=ids_texto(objetos))
    return queryset.filter(permitido)
