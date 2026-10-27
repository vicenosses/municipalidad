"""Operaciones del aporte: permisos, concurrencia, historial y auditoría."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from atenciones.models import AtencionCiudadana
from auditoria.utils import registrar_auditoria
from evidencias.models import Evidencia
from evidencias.consultas import tiene_evidencia_aprobada
from sgr.models import AporteIndicador, EventoAporte, Indicador
from sgr.plazos import dentro_plazo
from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa, en_contexto_delegacion

ROLES_VALIDACION = ('administrador', 'delegado', 'verificador')


def indicadores_para_actividad(fecha, delegacion):
    if not fecha or not delegacion:
        return Indicador.objects.none()
    return Indicador.objects.filter(
        activo=True, meta__activo=True, meta__delegacion=delegacion, meta__periodo__activo=True,
        meta__periodo__fecha_inicio__lte=fecha, meta__periodo__fecha_fin__gte=fecha,
    ).select_related('meta__periodo', 'meta__delegacion')


def aportes_visibles(request):
    qs = AporteIndicador.objects.select_related(
        'actividad__delegacion', 'indicador__meta__periodo', 'indicador__meta__delegacion', 'validado_por',
    )
    rol = obtener_rol(request.user)
    if rol not in (*ROLES_VALIDACION, 'coordinador', 'funcionario'):
        return qs.none()
    delegacion = get_delegacion_activa(request)
    if rol == 'administrador' and delegacion is None:
        return qs
    return qs.filter(actividad__delegacion=delegacion,
                     indicador__meta__delegacion=delegacion) if delegacion else qs.none()


def puede_proponer(request, actividad, aporte=None):
    rol = obtener_rol(request.user)
    alcance = en_contexto_delegacion(request, actividad.delegacion)
    if not (rol in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador')
            and alcance and actividad.responsable_id == request.user.pk and actividad.activo):
        return False
    if aporte:
        if aporte.estado == AporteIndicador.Estado.REQUIERE_CORRECCION:
            return True
        if aporte.estado != AporteIndicador.Estado.PENDIENTE or aporte.espera_cierre:
            return False
    return dentro_plazo(actividad.fecha)


def puede_revisar(request, aporte):
    rol = obtener_rol(request.user)
    return (
        rol in ROLES_VALIDACION
        and aporte.actividad.creado_por_id != request.user.pk
        and en_contexto_delegacion(request, aporte.actividad.delegacion)
        and en_contexto_delegacion(request, aporte.indicador.meta.delegacion)
    )


def pendientes_validacion(request):
    if obtener_rol(request.user) not in ROLES_VALIDACION:
        return AporteIndicador.objects.none()
    return aportes_visibles(request).filter(
        estado=AporteIndicador.Estado.PENDIENTE, actividad__activo=True,
        actividad__evidencias__estado=Evidencia.Estado.APROBADA,
        indicador__activo=True, indicador__meta__activo=True, indicador__meta__periodo__activo=True,
    ).filter(Q(espera_cierre=False) | Q(actividad__estado=AtencionCiudadana.Estado.CERRADA)
    ).exclude(actividad__creado_por=request.user).distinct()


def instantanea(aporte):
    return dict(indicador_id=aporte.indicador_id, estado=aporte.estado,
                valor_declarado=aporte.valor_declarado, valor_validado=aporte.valor_validado)


def registrar_evento(request, aporte, accion, anterior=None, comentario=None):
    anterior = anterior or {}
    EventoAporte.objects.create(
        aporte=aporte, accion=accion, indicador_anterior_id=anterior.get('indicador_id'),
        indicador_nuevo_id=aporte.indicador_id, estado_anterior=anterior.get('estado', ''),
        estado_nuevo=aporte.estado, declarado_anterior=anterior.get('valor_declarado'),
        declarado_nuevo=aporte.valor_declarado, validado_anterior=anterior.get('valor_validado'),
        validado_nuevo=aporte.valor_validado, comentario=aporte.comentario if comentario is None else comentario,
        corregir_indicador=aporte.corregir_indicador, corregir_valor=aporte.corregir_valor,
        usuario=request.user, version=aporte.version,
    )
    registrar_auditoria(request, accion, aporte,
                        f'Actividad {aporte.actividad_id}; Indicador {aporte.indicador_id}; '
                        f'{aporte.get_estado_display()}. {aporte.comentario}')


def guardar_version(aporte, version):
    aporte.full_clean()
    campos = ('indicador_id', 'estado', 'valor_declarado', 'valor_validado', 'comentario',
              'validado_por_id', 'validado_en', 'corregir_indicador', 'corregir_valor', 'espera_cierre')
    cambios = {campo: getattr(aporte, campo) for campo in campos}
    cambios.update(version=F('version') + 1, actualizado_en=timezone.now())
    if AporteIndicador.objects.filter(pk=aporte.pk, version=version).update(**cambios) != 1:
        raise ValidationError('El aporte cambió mientras revisaba la página. Recargue antes de continuar.')
    aporte.version = version + 1


@transaction.atomic
def proponer_aporte(request, actividad, indicador, valor_declarado, version=0):
    valor = valor_declarado
    actividad = AtencionCiudadana.objects.select_for_update().get(pk=actividad.pk)
    aporte = AporteIndicador.objects.select_for_update().filter(actividad=actividad).first()
    if not puede_proponer(request, actividad, aporte):
        raise PermissionDenied('No puede cambiar el aporte: revise el plazo, estado y responsable.')
    if aporte and aporte.version != version:
        raise ValidationError('El aporte cambió. Recargue la página antes de reenviar.')
    if not indicadores_para_actividad(actividad.fecha, actividad.delegacion).filter(pk=indicador.pk).exists():
        raise ValidationError('El Indicador no es válido para la fecha y Delegación de la Actividad.')
    if aporte is None:
        if version != 0:
            raise ValidationError('La asociación cambió. Recargue la página.')
        aporte = AporteIndicador(actividad=actividad, indicador=indicador, valor_declarado=valor)
        aporte.full_clean()
        aporte.save()
        registrar_evento(request, aporte, 'asociar_indicador')
        registrar_evento(request, aporte, 'enviar_aporte', instantanea(aporte))
        return aporte
    anterior = instantanea(aporte)
    correccion = aporte.estado == AporteIndicador.Estado.REQUIERE_CORRECCION
    if correccion:
        if indicador.pk != aporte.indicador_id and not aporte.corregir_indicador:
            raise ValidationError('La revisión no autorizó cambiar el Indicador.')
        if valor != aporte.valor_declarado and not aporte.corregir_valor:
            raise ValidationError('La revisión no autorizó cambiar el valor declarado.')
    if indicador.pk == aporte.indicador_id and valor == aporte.valor_declarado:
        if correccion:
            raise ValidationError('Realice la corrección solicitada antes de reenviar.')
        return aporte
    aporte.indicador = indicador
    aporte.valor_declarado = valor
    aporte.estado = AporteIndicador.Estado.PENDIENTE
    aporte.valor_validado = aporte.validado_por = aporte.validado_en = None
    aporte.comentario = ''
    aporte.corregir_indicador = aporte.corregir_valor = aporte.espera_cierre = False
    guardar_version(aporte, version)
    registrar_evento(request, aporte, 'corregir_aporte' if correccion else 'cambiar_indicador', anterior)
    registrar_evento(request, aporte, 'reenviar_aporte', instantanea(aporte))
    return aporte


@transaction.atomic
def validar_aporte(request, pk, version, estado, valor_validado=None, comentario='',
                   corregir_indicador=False, corregir_valor=False):
    actividad_id = AporteIndicador.objects.values_list('actividad_id', flat=True).get(pk=pk)
    AtencionCiudadana.objects.select_for_update().get(pk=actividad_id)
    aporte = AporteIndicador.objects.select_for_update().get(pk=pk)
    if not puede_revisar(request, aporte):
        raise PermissionDenied('No puede validar este aporte ni autovalidar una Actividad propia.')
    if aporte.estado != AporteIndicador.Estado.PENDIENTE or aporte.version != version:
        raise ValidationError('El aporte ya fue revisado o cambió. Recargue la página.')
    if not aporte.actividad.activo:
        raise ValidationError('La Actividad debe estar habilitada para validar su aporte.')
    if aporte.espera_cierre and aporte.actividad.estado != AtencionCiudadana.Estado.CERRADA:
        raise ValidationError('La Actividad reabierta debe cerrarse antes de una nueva validación.')
    if not tiene_evidencia_aprobada(aporte.actividad):
        raise ValidationError('La Actividad necesita al menos una evidencia aprobada.')
    if estado not in (AporteIndicador.Estado.CUMPLE, AporteIndicador.Estado.NO_CUMPLE,
                      AporteIndicador.Estado.REQUIERE_CORRECCION):
        raise ValidationError('Seleccione una decisión válida.')
    anterior = instantanea(aporte)
    aporte.estado = estado
    aporte.comentario = comentario.strip()
    aporte.valor_validado = (
        (aporte.valor_declarado if valor_validado is None else valor_validado)
        if estado == AporteIndicador.Estado.CUMPLE else None
    )
    aporte.validado_por = request.user
    aporte.validado_en = timezone.now()
    aporte.corregir_indicador = corregir_indicador if estado == AporteIndicador.Estado.REQUIERE_CORRECCION else False
    aporte.corregir_valor = corregir_valor if estado == AporteIndicador.Estado.REQUIERE_CORRECCION else False
    aporte.espera_cierre = False
    guardar_version(aporte, version)
    accion = {AporteIndicador.Estado.CUMPLE: 'validar_aporte',
              AporteIndicador.Estado.REQUIERE_CORRECCION: 'requerir_correccion_aporte',
              AporteIndicador.Estado.NO_CUMPLE: 'no_cumple_aporte'}[estado]
    registrar_evento(request, aporte, accion, anterior)
    return aporte


@transaction.atomic
def reiniciar_por_reapertura(request, actividad):
    aporte = AporteIndicador.objects.select_for_update().filter(
        actividad=actividad, estado=AporteIndicador.Estado.CUMPLE).first()
    if aporte:
        anterior = instantanea(aporte)
        version = aporte.version
        aporte.estado = AporteIndicador.Estado.PENDIENTE
        aporte.valor_validado = aporte.validado_por = aporte.validado_en = None
        aporte.comentario = ''
        aporte.espera_cierre = True
        guardar_version(aporte, version)
        registrar_evento(request, aporte, 'reiniciar_aporte_reapertura', anterior,
                         comentario='La Actividad se reabrió; requiere cierre y nueva validación.')
