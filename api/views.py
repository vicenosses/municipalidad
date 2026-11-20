from datetime import datetime
from pathlib import Path
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.db.models import F, Min, Prefetch, Value
from django.db.models.functions import Coalesce, Replace, Upper
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiTypes, OpenApiResponse

from agenda.forms import CompromisoForm, SolicitudAmpliacionForm, SeguimientoCompromisoForm
from agenda.models import Compromiso, HistorialCompromiso, SolicitudAmpliacion
from agenda.views import compromisos_visibles
from atenciones.estados import cambiar_estado_actividad, registrar_creacion_actividad
from atenciones.forms import AtencionCiudadanaForm, AtencionEditarForm
from atenciones.models import AtencionCiudadana
from atenciones.permisos import puede_editar_actividad, queryset_atenciones
from atenciones.views import puede_cambiar_disponibilidad, puede_cambiar_va_al_tubo
from auditoria.models import RegistroAuditoria
from auditoria.utils import registrar_auditoria
from cartas.models import Carta
from catalogos.models import SubAtencion, TipoAtencion
from catalogos.forms import SubAtencionForm, TipoAtencionForm
from catalogos.permisos import catalogos_editables
from config.eliminacion import relaciones_existentes
from django.db.models.deletion import ProtectedError, RestrictedError
from evidencias.forms import ValidacionEvidenciaForm
from evidencias.models import Evidencia
from evidencias.permisos import puede_validar_evidencia
from evidencias.views import EvidenciaValidarView, evidencias_visibles
from gestion_social.models import GestionSocial
from hitos.models import Hito
from sgr.aportes import aportes_visibles, pendientes_validacion, proponer_aporte, validar_aporte
from sgr.dashboard import construir_dashboard
from sgr.models import AporteIndicador, AsignacionMeta, Indicador, Meta, Periodo
from usuarios.limite_ingreso import esta_bloqueado, limpiar_intentos, registrar_fallo
from usuarios.auth_views import MENSAJE_GENERICO, solicitar_recuperacion
from usuarios.mixins import obtener_rol
from usuarios.models import Cargo, Delegacion, Rol, Territorio, Vecino
from usuarios.sesion import DELEGACION_SESION, delegaciones_autorizadas, get_delegacion_activa

from api.access import ROLES_GESTORES, ROLES_VALIDOS, etiqueta_usuario, filtro_hito_delegacion, filtrar_delegaciones, rol_usuario, usuario_puede_ver_detalle
from api.permissions import RolesPermitidos
from api.esquemas import TipoEntradaSerializer, SubAtencionEntradaSerializer, ActividadEntradaSerializer, ActividadEditarSerializer, RecuperacionEntradaSerializer
from api.serializers import (
    AporteSerializer,
    AsignacionMetaSerializer,
    AtencionSerializer,
    AtencionAdministradorSerializer,
    AuditoriaSerializer,
    CartaSerializer,
    CargoSerializer,
    CompromisoSerializer,
    SeguimientoCompromisoSerializer,
    DelegacionSerializer,
    EvidenciaCreateSerializer,
    EvidenciaSerializer,
    GestionSocialSerializer,
    SeguimientoGestionSocialSerializer,
    HitoSerializer,
    IndicadorSerializer,
    MetaSerializer,
    MiPerfilSerializer,
    PeriodoSerializer,
    ProponerAporteSerializer,
    RolSerializer,
    SubAtencionSerializer,
    TerritorioSerializer,
    TipoAtencionSerializer,
    VecinoResumenSerializer,
    VecinoAdministradorSerializer,
    ValidarAporteSerializer,
)

THROTTLE_SCOPE_RECUPERACION = 'solicitud_recuperacion'
MENSAJE_BOOLEANO_INVALIDO = 'Use true o false.'
MENSAJE_TRANSICION_INVALIDA = 'La transición de estado no está permitida.'
ETIQUETA_GESTION_SOCIAL = 'Gestión social'
RESPUESTAS_ERROR_API = {
    400: OpenApiResponse(description='Datos inválidos o existen registros relacionados.'),
    401: OpenApiResponse(description='Debe autenticarse con un token válido.'),
    403: OpenApiResponse(description='Su rol no permite realizar esta operación.'),
    404: OpenApiResponse(description='El registro no existe o no está dentro de su ámbito.'),
    500: OpenApiResponse(description='Error interno sin detalles sensibles.'),
}


class AccesoTokenSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        identificador = attrs.get(self.username_field, '')
        if esta_bloqueado(identificador):
            raise AuthenticationFailed('Credenciales no válidas o cuenta temporalmente bloqueada.')
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            registrar_fallo(identificador)
            raise
        if obtener_rol(self.user) not in ROLES_VALIDOS:
            registrar_fallo(identificador)
            raise AuthenticationFailed('Credenciales no válidas o cuenta no habilitada para la API.')
        limpiar_intentos(identificador)
        return data


class AccesoTokenView(TokenObtainPairView):
    serializer_class = AccesoTokenSerializer
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AnonRateThrottle, ScopedRateThrottle)
    throttle_scope = 'login'


class SalirTokenView(TokenBlacklistView):
    permission_classes = (IsAuthenticated,)


class RecuperacionAPIView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (AnonRateThrottle, ScopedRateThrottle)
    throttle_scope = THROTTLE_SCOPE_RECUPERACION

    @extend_schema(request=RecuperacionEntradaSerializer, responses={202: OpenApiTypes.OBJECT}, auth=[])
    def post(self, request):
        identificador = (request.data.get('identificador') or '').strip()
        if not identificador or len(identificador) > 254:
            raise ValidationError({'identificador': 'Ingrese un correo o nombre de usuario válido.'})
        solicitar_recuperacion(request, identificador)
        return Response({'detail': MENSAJE_GENERICO}, status=status.HTTP_202_ACCEPTED)


class MiPerfilView(APIView):
    @extend_schema(responses=MiPerfilSerializer)
    def get(self, request):
        return Response(MiPerfilSerializer(request.user).data)


class BaseViewSet:
    roles_por_accion = {}
    http_method_names = ('get', 'post', 'head', 'options')

    def get_permissions(self):
        return [IsAuthenticated(), RolesPermitidos()]


class ReadOnlyViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    pass


class DelegacionViewSet(ReadOnlyViewSet):
    serializer_class = DelegacionSerializer
    queryset = Delegacion.objects.all()

    def get_queryset(self):
        return delegaciones_autorizadas(self.request.user)


class TerritorioViewSet(ReadOnlyViewSet):
    serializer_class = TerritorioSerializer
    queryset = Territorio.objects.all()

    def get_queryset(self):
        return filtrar_delegaciones(
            Territorio.objects.filter(activo=True).select_related('delegacion'),
            self.request.user,
        )


class CatalogoGestorViewSet(ReadOnlyViewSet):
    roles_por_accion = {
        'list': ROLES_GESTORES,
        'retrieve': ROLES_GESTORES,
    }


class CargoViewSet(CatalogoGestorViewSet):
    serializer_class = CargoSerializer
    queryset = Cargo.objects.all()

    def get_queryset(self):
        return Cargo.objects.filter(activo=True)


class RolViewSet(CatalogoGestorViewSet):
    serializer_class = RolSerializer
    queryset = Rol.objects.all()

    def get_queryset(self):
        return Rol.objects.filter(activo=True)


class CatalogoEditableMixin:
    http_method_names = ('get', 'post', 'put', 'delete', 'head', 'options')
    roles_por_accion = {
        'list': ROLES_VALIDOS, 'retrieve': ROLES_VALIDOS,
        'create': ('administrador', 'delegado', 'coordinador'),
        'update': ('administrador', 'delegado', 'coordinador'),
        'destroy': ('administrador',),
    }

    def _guardar(self, request, instance=None):
        datos = request.data.copy()
        if 'activo' not in datos:
            datos['activo'] = instance.activo if instance is not None else True
        if (instance is not None and 'delegacion' not in datos and
                rol_usuario(request.user) == 'administrador' and get_delegacion_activa(request) is None):
            datos['delegacion'] = instance.delegacion_id or ''
        form = self.form_class(datos, instance=instance, request=request)
        if not form.is_valid():
            return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            try:
                objeto = form.save()
            except DjangoValidationError as error:
                raise ValidationError(getattr(error, 'message_dict', error.messages)) from error
            registrar_auditoria(request, 'editar' if instance else 'crear', objeto,
                                f'Catálogo {objeto.pk} actualizado desde API.')
        return Response(self.get_serializer(objeto).data,
                        status=status.HTTP_200_OK if instance else status.HTTP_201_CREATED)

    def create(self, request, *args, **kwargs):
        return self._guardar(request)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            return self._guardar(request, self.get_object())

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            objeto = self.get_object()
            relaciones = relaciones_existentes(objeto)
            if relaciones:
                raise ValidationError({'detail': 'No se puede eliminar: existen registros relacionados (' + ', '.join(relaciones) + ').'})
            try:
                registrar_auditoria(request, 'eliminar', objeto, f'Catálogo {objeto.pk} eliminado desde API.')
                objeto.delete()
            except (ProtectedError, RestrictedError) as error:
                raise ValidationError({'detail': 'No se puede eliminar porque existen registros relacionados.'}) from error
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_queryset(self):
        queryset = self.catalogo_model.objects.all()
        if self.action in ('update', 'destroy'):
            return catalogos_editables(queryset.select_for_update(), self.request)
        return self.queryset_visible()


@extend_schema_view(
    create=extend_schema(request=TipoEntradaSerializer, responses={201: TipoAtencionSerializer, **RESPUESTAS_ERROR_API}),
    update=extend_schema(request=TipoEntradaSerializer, responses={200: TipoAtencionSerializer, **RESPUESTAS_ERROR_API}),
    destroy=extend_schema(description='Solo administrador. Se bloquea si hay registros relacionados.', responses={204: None, **RESPUESTAS_ERROR_API}),
)
class TipoAtencionViewSet(CatalogoEditableMixin, ReadOnlyViewSet):
    serializer_class = TipoAtencionSerializer
    queryset = TipoAtencion.objects.all()
    catalogo_model = TipoAtencion
    form_class = TipoAtencionForm

    def get_queryset(self):
        return super().get_queryset()

    def queryset_visible(self):
        return TipoAtencion.objects.filter(activo=True).filter(
            Q(es_general=True) | Q(delegacion__in=delegaciones_autorizadas(self.request.user))
        )


@extend_schema_view(
    create=extend_schema(request=SubAtencionEntradaSerializer, responses={201: SubAtencionSerializer, **RESPUESTAS_ERROR_API}),
    update=extend_schema(request=SubAtencionEntradaSerializer, responses={200: SubAtencionSerializer, **RESPUESTAS_ERROR_API}),
    destroy=extend_schema(description='Solo administrador. Se bloquea si hay registros relacionados.', responses={204: None, **RESPUESTAS_ERROR_API}),
)
class SubAtencionViewSet(CatalogoEditableMixin, ReadOnlyViewSet):
    serializer_class = SubAtencionSerializer
    queryset = SubAtencion.objects.all()
    catalogo_model = SubAtencion
    form_class = SubAtencionForm

    def get_queryset(self):
        return super().get_queryset()

    def queryset_visible(self):
        return SubAtencion.objects.filter(activo=True, tipo__activo=True).filter(
            Q(es_general=True) | Q(delegacion__in=delegaciones_autorizadas(self.request.user))
        ).select_related('tipo')


class VecinoViewSet(ReadOnlyViewSet):
    serializer_class = VecinoResumenSerializer
    queryset = Vecino.objects.all()
    roles_por_accion = {'list': ROLES_VALIDOS, 'retrieve': ROLES_VALIDOS}

    def get_serializer_class(self):
        return VecinoAdministradorSerializer if rol_usuario(self.request.user) == 'administrador' else VecinoResumenSerializer

    def get_queryset(self):
        queryset = Vecino.objects.filter(
            territorio__delegacion__in=delegaciones_autorizadas(self.request.user),
        )
        if rol_usuario(self.request.user) != 'administrador':
            queryset = queryset.filter(activo=True).only('id', 'nombres', 'apellidos', 'rut', 'territorio_id')
        if self.action == 'retrieve' and rol_usuario(self.request.user) == 'administrador':
            return queryset
        busqueda = (self.request.query_params.get('q') or '').strip()
        if len(busqueda) < 2:
            return queryset.none()
        if re.fullmatch(r'[0-9.\-\sKk]+', busqueda):
            rut = re.sub(r'[.\-\s]', '', busqueda).upper()
            if not rut:
                return queryset.none()
            return queryset.annotate(
                rut_normalizado=Upper(Replace(
                    Replace(Replace(F('rut'), Value('.'), Value('')), Value('-'), Value('')),
                    Value(' '), Value(''),
                )),
            ).filter(rut_normalizado=rut)
        return queryset.filter(Q(nombres__icontains=busqueda) | Q(apellidos__icontains=busqueda))


class PeriodoViewSet(ReadOnlyViewSet):
    serializer_class = PeriodoSerializer
    queryset = Periodo.objects.all()
    roles_por_accion = {
        'list': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'retrieve': (*ROLES_GESTORES, 'funcionario', 'verificador'),
    }


class MetaViewSet(ReadOnlyViewSet):
    serializer_class = MetaSerializer
    queryset = Meta.objects.all()
    roles_por_accion = {
        'list': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'retrieve': (*ROLES_GESTORES, 'funcionario', 'verificador'),
    }

    def get_queryset(self):
        return filtrar_delegaciones(
            Meta.objects.select_related('periodo', 'delegacion'),
            self.request.user,
        )


class AsignacionMetaViewSet(ReadOnlyViewSet):
    serializer_class = AsignacionMetaSerializer
    queryset = AsignacionMeta.objects.all()
    roles_por_accion = {'list': ROLES_VALIDOS, 'retrieve': ROLES_VALIDOS}

    def get_queryset(self):
        queryset = filtrar_delegaciones(
            AsignacionMeta.objects.select_related('meta__periodo', 'meta__delegacion', 'funcionario'),
            self.request.user,
            'meta__delegacion',
        )
        if rol_usuario(self.request.user) == 'funcionario':
            return queryset.filter(funcionario=self.request.user)
        return queryset


class IndicadorViewSet(ReadOnlyViewSet):
    serializer_class = IndicadorSerializer
    queryset = Indicador.objects.all()
    roles_por_accion = {'list': ROLES_VALIDOS, 'retrieve': ROLES_VALIDOS}

    def get_queryset(self):
        return filtrar_delegaciones(
            Indicador.objects.select_related('meta__periodo', 'meta__delegacion'),
            self.request.user,
            'meta__delegacion',
        )


@extend_schema_view(
    create=extend_schema(request=ActividadEntradaSerializer, responses={201: AtencionSerializer, **RESPUESTAS_ERROR_API},
        examples=[OpenApiExample('Actividad', value={'titulo': 'Atención vecinal', 'fecha': '2026-11-18', 'solicitante': 'Persona de prueba', 'tipo': 1, 'subatencion': 1, 'descripcion': 'Orientación realizada.', 'delegacion': 1}, request_only=True)]),
    update=extend_schema(request=ActividadEditarSerializer, responses={200: AtencionSerializer, **RESPUESTAS_ERROR_API}),
    partial_update=extend_schema(request=ActividadEditarSerializer, responses={200: AtencionSerializer, **RESPUESTAS_ERROR_API}),
    destroy=extend_schema(description='Solo administrador. Se bloquea si hay registros relacionados.', responses={204: None, **RESPUESTAS_ERROR_API}),
)
class AtencionViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AtencionCiudadana.objects.all()
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ROLES_VALIDOS,
        'update': ROLES_VALIDOS,
        'partial_update': ROLES_VALIDOS,
        'destroy': ('administrador',),
        'estado': ROLES_VALIDOS,
        'tubo': ROLES_VALIDOS,
        'disponibilidad': ('administrador', 'delegado'),
    }
    http_method_names = ('get', 'post', 'put', 'patch', 'delete', 'head', 'options')

    def get_serializer_class(self):
        if rol_usuario(self.request.user) == 'administrador' and self.action != 'list':
            return AtencionAdministradorSerializer
        return AtencionSerializer

    def get_queryset(self):
        _seleccionar_delegacion(self.request)
        return queryset_atenciones(self.request).select_related(None).select_related(
            'responsable',
        ).prefetch_related(
            Prefetch('evidencias', queryset=Evidencia.objects.only('id', 'estado', 'reemplaza_id')),
        ).defer('solicitante', 'descripcion')

    def create(self, request, *args, **kwargs):
        _seleccionar_delegacion(request)
        form = AtencionCiudadanaForm(request.data, request.FILES, request=request)
        if not form.is_valid():
            return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
        delegacion = get_delegacion_activa(request)
        if delegacion is None:
            raise ValidationError({'delegacion': 'Seleccione una delegación autorizada.'})
        with transaction.atomic():
            atencion = form.save(commit=False)
            atencion.delegacion = delegacion
            atencion.responsable = request.user
            atencion.creado_por = request.user
            atencion.estado = AtencionCiudadana.Estado.REGISTRADA
            try:
                atencion.save()
            except DjangoValidationError as error:
                raise ValidationError(getattr(error, 'message_dict', error.messages)) from error
            registrar_creacion_actividad(atencion, request.user)
            if form.cleaned_data.get('va_al_tubo'):
                compromiso = Compromiso.objects.create(
                    titulo=atencion.titulo,
                    descripcion=atencion.descripcion,
                    solicitante=atencion.solicitante,
                    fecha_hora=form.cleaned_data['plazo_tubo'],
                    rut_solicitante=form.cleaned_data.get('rut_tubo', ''),
                    telefono_solicitante=form.cleaned_data.get('telefono_tubo', ''),
                    responsable=request.user,
                    creado_por=request.user,
                    delegacion=delegacion,
                )
                compromiso.actividades.add(atencion)
                HistorialCompromiso.objects.create(
                    compromiso=compromiso,
                    campo='creacion',
                    valor_nuevo=compromiso.get_estado_display(),
                    realizado_por=request.user,
                )
            registrar_auditoria(request, 'crear', atencion, f'Actividad {atencion.pk} creada.')
            if form.cleaned_data.get('indicador'):
                try:
                    proponer_aporte(
                        request,
                        atencion,
                        form.cleaned_data['indicador'],
                        form.cleaned_data.get('valor_declarado'),
                    )
                except DjangoValidationError as error:
                    raise ValidationError(getattr(error, 'message_dict', error.messages)) from error
        return Response(self.get_serializer(atencion).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            visible = self.get_object()
            actual = get_object_or_404(queryset_atenciones(request).select_for_update(), pk=visible.pk)
            if not puede_editar_actividad(request, actual):
                raise PermissionDenied('No puede editar esta actividad.')
            campos = ('titulo', 'fecha', 'solicitante', 'territorio', 'descripcion')
            desconocidos = set(request.data) - set(campos)
            if desconocidos:
                raise ValidationError({'detail': 'Solo se pueden modificar los datos descriptivos autorizados.'})
            datos = dict(request.data)
            if kwargs.get('partial'):
                iniciales = {'titulo': actual.titulo, 'fecha': actual.fecha.isoformat(),
                             'solicitante': actual.solicitante, 'territorio': actual.territorio_id or '',
                             'descripcion': actual.descripcion}
                iniciales.update(datos)
                datos = iniciales
            form = AtencionEditarForm(datos, instance=actual)
            if form.fields['fecha'].disabled and 'fecha' in request.data and str(request.data['fecha']) != actual.fecha.isoformat():
                raise ValidationError({'fecha': 'No se puede cambiar la fecha con compromisos o aportes vinculados.'})
            if not form.is_valid():
                return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
            try:
                objeto = form.save()
            except DjangoValidationError as error:
                raise ValidationError(getattr(error, 'message_dict', error.messages)) from error
            registrar_auditoria(request, 'editar_actividad', objeto, 'Datos descriptivos modificados desde API.')
            return Response(self.get_serializer(objeto).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        with transaction.atomic():
            visible = self.get_object()
            objeto = get_object_or_404(queryset_atenciones(request).select_for_update(), pk=visible.pk)
            relaciones = relaciones_existentes(objeto)
            if relaciones:
                raise ValidationError({'detail': 'No se puede eliminar: existen registros relacionados (' + ', '.join(relaciones) + ').'})
            try:
                registrar_auditoria(request, 'eliminar', objeto, f'Actividad {objeto.pk} eliminada desde API.')
                objeto.historial_estados.all().delete()
                objeto.delete()
            except (ProtectedError, RestrictedError) as error:
                raise ValidationError({'detail': 'No se puede eliminar porque existen registros relacionados.'}) from error
            except DjangoValidationError as error:
                raise ValidationError(error.messages) from error
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=('post',), url_path='estado')
    def estado(self, request, pk=None):
        atencion = self.get_object()
        try:
            actualizada = cambiar_estado_actividad(
                request, atencion.pk, request.data.get('estado'), request.data.get('motivo', ''),
            )
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(self.get_serializer(actualizada).data)

    @action(detail=True, methods=('post',), url_path='tubo')
    def tubo(self, request, pk=None):
        atencion = self.get_object()
        if not puede_cambiar_va_al_tubo(request, atencion):
            raise PermissionDenied('No puede cambiar la inclusión de esta actividad en el tubo.')
        valor = request.data.get('va_al_tubo')
        if not isinstance(valor, bool):
            raise ValidationError({'va_al_tubo': MENSAJE_BOOLEANO_INVALIDO})
        if valor and not atencion.compromisos.exists():
            raise ValidationError('Cree un compromiso con plazo antes de incluir la actividad en el tubo.')
        if not valor and atencion.compromisos.exists():
            raise ValidationError('No se puede retirar una actividad que tiene compromisos asociados.')
        if atencion.va_al_tubo != valor:
            previo = atencion.va_al_tubo
            atencion.va_al_tubo = valor
            atencion.save(update_fields=['va_al_tubo'])
            registrar_auditoria(request, 'cambiar_va_al_tubo', atencion, f'Va al tubo: {previo} → {valor}.')
        return Response(self.get_serializer(atencion).data)

    @action(detail=True, methods=('post',), url_path='disponibilidad')
    def disponibilidad(self, request, pk=None):
        atencion = self.get_object()
        if not puede_cambiar_disponibilidad(request, atencion):
            raise PermissionDenied('No puede cambiar la disponibilidad de esta actividad.')
        valor = request.data.get('activo')
        if not isinstance(valor, bool):
            raise ValidationError({'activo': MENSAJE_BOOLEANO_INVALIDO})
        atencion.activo = valor
        atencion.save(update_fields=['activo'])
        registrar_auditoria(
            request, 'habilitar' if valor else 'deshabilitar', atencion,
            f'Actividad {atencion.pk}: activo={valor}.',
        )
        return Response(self.get_serializer(atencion).data)


class CompromisoViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Compromiso.objects.all()
    serializer_class = CompromisoSerializer
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ROLES_VALIDOS,
        'solicitar_ampliacion': ROLES_VALIDOS,
        'seguimientos': ROLES_VALIDOS,
    }

    def get_queryset(self):
        _seleccionar_delegacion(self.request)
        return compromisos_visibles(self.request).select_related(None).prefetch_related(None).select_related(
            'responsable',
        ).prefetch_related(
            Prefetch('actividades', queryset=AtencionCiudadana.objects.only('id')),
        ).defer('solicitante', 'rut_solicitante', 'telefono_solicitante', 'observaciones')

    def create(self, request, *args, **kwargs):
        _seleccionar_delegacion(request)
        delegacion = get_delegacion_activa(request)
        if delegacion is None:
            raise ValidationError({'delegacion': 'Seleccione una delegación autorizada.'})
        form = CompromisoForm(
            request.data,
            delegacion=delegacion,
            delegaciones=[delegacion],
            user=request.user,
            es_creacion=True,
        )
        if not form.is_valid():
            return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            compromiso = form.save(commit=False)
            compromiso.delegacion = delegacion
            compromiso.creado_por = request.user
            compromiso.estado = Compromiso.Estado.INGRESADO
            compromiso.save()
            form.save_m2m()
            compromiso.actividades.filter(va_al_tubo=False).update(va_al_tubo=True)
            HistorialCompromiso.objects.create(
                compromiso=compromiso, campo='creacion',
                valor_nuevo=compromiso.get_estado_display(), realizado_por=request.user,
            )
            registrar_auditoria(request, 'crear', compromiso, f'Compromiso {compromiso.codigo} creado.')
        return Response(self.get_serializer(compromiso).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('get', 'post'), url_path='seguimientos')
    def seguimientos(self, request, pk=None):
        from agenda.seguimientos import registrar_seguimiento
        compromiso = self.get_object()
        if not usuario_puede_ver_detalle(request.user, compromiso):
            raise PermissionDenied('No puede consultar el seguimiento de este compromiso.')
        if request.method == 'GET':
            queryset = compromiso.historial.filter(campo__in=('avance', 'observacion')).select_related('realizado_por').order_by('-creado', '-pk')
            pagina = self.paginate_queryset(queryset)
            serializer = SeguimientoCompromisoSerializer(pagina if pagina is not None else queryset, many=True)
            return self.get_paginated_response(serializer.data) if pagina is not None else Response(serializer.data)
        form = SeguimientoCompromisoForm(request.data)
        if not form.is_valid():
            return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
        evento = registrar_seguimiento(request, compromiso.pk, **form.cleaned_data)
        return Response(SeguimientoCompromisoSerializer(evento).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('post',), url_path='solicitar-ampliacion')
    def solicitar_ampliacion(self, request, pk=None):
        visible = self.get_object()
        with transaction.atomic():
            compromiso = Compromiso.objects.select_for_update().get(pk=visible.pk)
            if compromiso.responsable_id != request.user.pk or compromiso.estado == Compromiso.Estado.REALIZADO:
                raise PermissionDenied('Solo la persona responsable puede solicitar una ampliación pendiente.')
            if compromiso.solicitudes_ampliacion.filter(estado=SolicitudAmpliacion.Estado.PENDIENTE).exists():
                raise ValidationError('Ya existe una solicitud pendiente para este compromiso.')
            form = SolicitudAmpliacionForm(request.data, compromiso=compromiso)
            if not form.is_valid():
                return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
            solicitud = form.save(commit=False)
            solicitud.compromiso = compromiso
            solicitud.solicitante = request.user
            solicitud.plazo_anterior = compromiso.fecha_hora
            solicitud.save()
            registrar_auditoria(request, 'solicitar_ampliacion', compromiso, 'Solicitud de ampliación creada.')
        return Response({
            'id': solicitud.pk,
            'compromiso': compromiso.codigo,
            'estado': solicitud.estado,
            'plazo_propuesto': solicitud.plazo_propuesto,
        }, status=status.HTTP_201_CREATED)


class AmpliacionSerializer(serializers.ModelSerializer):
    solicitante = serializers.CharField(source='solicitante.username', read_only=True)
    compromiso_codigo = serializers.CharField(source='compromiso.codigo', read_only=True)

    class Meta:
        model = SolicitudAmpliacion
        fields = (
            'id', 'compromiso', 'compromiso_codigo', 'solicitante', 'plazo_anterior',
            'plazo_propuesto', 'motivo', 'estado', 'creado', 'decidido_por', 'fecha_decision',
        )
        read_only_fields = fields


class AmpliacionViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AmpliacionSerializer
    queryset = SolicitudAmpliacion.objects.all()
    roles_por_accion = {
        'list': ('administrador', 'delegado', 'coordinador', 'verificador'),
        'retrieve': ('administrador', 'delegado', 'coordinador', 'verificador'),
        'decision': ('administrador', 'delegado', 'coordinador', 'verificador'),
    }

    def get_queryset(self):
        _seleccionar_delegacion(self.request)
        return SolicitudAmpliacion.objects.filter(
            compromiso__in=compromisos_visibles(self.request),
        ).select_related('compromiso', 'solicitante', 'decidido_por')

    @action(detail=True, methods=('post',), url_path='decision')
    def decision(self, request, pk=None):
        accion = request.data.get('accion')
        if accion not in ('aprobar', 'rechazar'):
            raise ValidationError({'accion': 'Use aprobar o rechazar.'})
        with transaction.atomic():
            solicitud = get_object_or_404(
                SolicitudAmpliacion.objects.select_for_update().select_related('compromiso'),
                pk=pk,
                compromiso__in=compromisos_visibles(request),
            )
            compromiso = Compromiso.objects.select_for_update().get(pk=solicitud.compromiso_id)
            if solicitud.estado != SolicitudAmpliacion.Estado.PENDIENTE:
                raise ValidationError('Esta solicitud ya fue resuelta.')
            if accion == 'aprobar' and (
                compromiso.estado == Compromiso.Estado.REALIZADO
                or compromiso.fecha_hora != solicitud.plazo_anterior
            ):
                raise ValidationError('El compromiso cambió; revise el plazo antes de aprobar.')
            if accion == 'aprobar':
                compromiso.fecha_hora = solicitud.plazo_propuesto
                compromiso.save(update_fields=['fecha_hora'])
                HistorialCompromiso.objects.create(
                    compromiso=compromiso,
                    campo='fecha_hora',
                    valor_anterior=solicitud.plazo_anterior.isoformat(),
                    valor_nuevo=solicitud.plazo_propuesto.isoformat(),
                    motivo=solicitud.motivo,
                    realizado_por=request.user,
                )
            solicitud.estado = (
                SolicitudAmpliacion.Estado.APROBADA if accion == 'aprobar'
                else SolicitudAmpliacion.Estado.RECHAZADA
            )
            solicitud.decidido_por = request.user
            solicitud.fecha_decision = timezone.now()
            solicitud.save(update_fields=['estado', 'decidido_por', 'fecha_decision'])
            registrar_auditoria(
                request, solicitud.estado, compromiso,
                f'Solicitud de ampliación {solicitud.pk} resuelta.',
            )
        return Response(self.get_serializer(solicitud).data)


class EvidenciaViewSet(
    BaseViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Evidencia.objects.all()
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ROLES_VALIDOS,
        'archivo': ROLES_VALIDOS,
        'validar': ('administrador', 'delegado', 'verificador'),
    }

    def get_serializer_class(self):
        return EvidenciaCreateSerializer if self.action == 'create' else EvidenciaSerializer

    def get_queryset(self):
        _seleccionar_delegacion(self.request)
        return evidencias_visibles(self.request).select_related(
            'atencion__delegacion', 'atencion__responsable', 'atencion__creado_por',
            'compromiso__delegacion', 'compromiso__responsable', 'compromiso__creado_por',
            'subido_por', 'validado_por',
        ).defer('archivo', 'comentario_validacion')

    def perform_create(self, serializer):
        evidencia = serializer.save()
        registrar_auditoria(
            self.request, 'subir_evidencia', evidencia,
            f'Evidencia {evidencia.codigo_respaldo} agregada.',
        )

    @action(detail=True, methods=('get',), url_path='archivo')
    def archivo(self, request, pk=None):
        evidencia = self.get_object()
        try:
            archivo = evidencia.archivo.open('rb')
        except FileNotFoundError as error:
            raise NotFound('El archivo de evidencia no está disponible.') from error
        extension = Path(evidencia.archivo.name).suffix.lower()
        response = FileResponse(
            archivo,
            as_attachment=True,
            filename=f'evidencia-{evidencia.pk}{extension}',
            content_type=evidencia.content_type,
        )
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response

    @action(detail=True, methods=('post',), url_path='validar')
    def validar(self, request, pk=None):
        evidencia = self.get_object()
        if not puede_validar_evidencia(request, evidencia):
            raise PermissionDenied('No puede validar esta evidencia.')
        accion = request.data.get('accion')
        if accion not in ('aprobar', 'rechazar'):
            raise ValidationError({'accion': 'Use aprobar o rechazar.'})
        form = ValidacionEvidenciaForm(request.data)
        if not form.is_valid():
            return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
        EvidenciaValidarView().guardar_decisiones(request, evidencia, form, accion, None, None)
        evidencia.refresh_from_db()
        return Response(EvidenciaSerializer(evidencia, context=self.get_serializer_context()).data)


class GestionSocialViewSet(BaseViewSet, viewsets.ModelViewSet):
    queryset = GestionSocial.objects.all()
    serializer_class = GestionSocialSerializer
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ROLES_VALIDOS,
        'update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'partial_update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'estado': ROLES_VALIDOS,
        'seguimientos': ROLES_VALIDOS,
        'disponibilidad': ROLES_GESTORES,
    }
    http_method_names = ('get', 'post', 'put', 'patch', 'head', 'options')

    def get_queryset(self):
        queryset = filtrar_delegaciones(
            GestionSocial.objects.select_related(
                'responsable', 'vecino',
            ).defer(
                'descripcion', 'vecino__telefono', 'vecino__correo', 'vecino__direccion',
            ),
            self.request.user,
        )
        if rol_usuario(self.request.user) in ('funcionario', 'verificador'):
            queryset = queryset.filter(Q(responsable=self.request.user) | Q(creado_por=self.request.user))
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        registrar_auditoria(
            self.request, 'crear_gestion_social', instance,
            f'{ETIQUETA_GESTION_SOCIAL} {instance.codigo} creada.',
        )

    def perform_update(self, serializer):
        instance = self.get_object()
        if not _puede_editar(self.request.user, instance):
            raise PermissionDenied('No puede editar esta gestión social.')
        if instance.estado == GestionSocial.Estado.CERRADA:
            raise ValidationError('No se puede editar una gestión social cerrada.')
        instance = serializer.save()
        registrar_auditoria(
            self.request, 'actualizar_gestion_social', instance,
            f'{ETIQUETA_GESTION_SOCIAL} {instance.codigo} actualizada.',
        )

    def destroy(self, request, *args, **kwargs):
        raise PermissionDenied('Los registros no se eliminan físicamente; solicite su desactivación.')

    @action(detail=True, methods=('get', 'post'), url_path='seguimientos')
    def seguimientos(self, request, pk=None):
        from operaciones.forms import SeguimientoGestionSocialForm
        visible = self.get_object()
        if request.method == 'GET':
            queryset = visible.seguimientos.select_related('autor')
            pagina = self.paginate_queryset(queryset)
            serializer = SeguimientoGestionSocialSerializer(pagina if pagina is not None else queryset, many=True)
            return self.get_paginated_response(serializer.data) if pagina is not None else Response(serializer.data)
        with transaction.atomic():
            gestion = GestionSocial.objects.select_for_update().get(pk=visible.pk)
            if not _puede_editar(request.user, gestion) or not gestion.activo or gestion.estado == GestionSocial.Estado.CERRADA:
                raise PermissionDenied('No puede agregar seguimiento a esta gestión.')
            form = SeguimientoGestionSocialForm(request.data)
            if not form.is_valid():
                return Response(form.errors.get_json_data(), status=status.HTTP_400_BAD_REQUEST)
            seguimiento = form.save(commit=False)
            seguimiento.gestion = gestion
            seguimiento.autor = request.user
            seguimiento.save()
            registrar_auditoria(request, 'agregar_seguimiento_gestion', gestion,
                                f'Seguimiento {seguimiento.pk} registrado para {gestion.codigo}.')
        serializer = SeguimientoGestionSocialSerializer(seguimiento)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('post',), url_path='estado')
    @transaction.atomic
    def estado(self, request, pk=None):
        visible = self.get_object()
        instance = GestionSocial.objects.select_for_update().get(pk=visible.pk)
        _validar_edicion(request.user, instance)
        nuevo = request.data.get('estado')
        transiciones = {
            GestionSocial.Estado.REGISTRADA: {GestionSocial.Estado.EN_PROCESO, GestionSocial.Estado.DERIVADA},
            GestionSocial.Estado.EN_PROCESO: {
                GestionSocial.Estado.PENDIENTE_ANTECEDENTES,
                GestionSocial.Estado.DERIVADA,
                GestionSocial.Estado.CERRADA,
            },
            GestionSocial.Estado.PENDIENTE_ANTECEDENTES: {
                GestionSocial.Estado.EN_PROCESO, GestionSocial.Estado.CERRADA,
            },
            GestionSocial.Estado.DERIVADA: {GestionSocial.Estado.EN_PROCESO, GestionSocial.Estado.CERRADA},
            GestionSocial.Estado.CERRADA: set(),
        }
        _validar_transicion_estado(instance, nuevo, transiciones)
        anterior = instance.estado
        instance.estado = nuevo
        instance.save(update_fields=['estado', 'actualizado_en'])
        registrar_auditoria(
            request, 'cambiar_estado_gestion_social', instance,
            f'{ETIQUETA_GESTION_SOCIAL} {instance.codigo}: {anterior} → {nuevo}.',
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=('post',), url_path='disponibilidad')
    def disponibilidad(self, request, pk=None):
        instance = self.get_object()
        if rol_usuario(request.user) not in ROLES_GESTORES:
            raise PermissionDenied('Solo un gestor puede desactivar una gestión social.')
        valor = request.data.get('activo')
        if not isinstance(valor, bool):
            raise ValidationError({'activo': MENSAJE_BOOLEANO_INVALIDO})
        instance.activo = valor
        instance.save(update_fields=['activo', 'actualizado_en'])
        registrar_auditoria(
            request, 'cambiar_disponibilidad_gestion_social', instance,
            f'{ETIQUETA_GESTION_SOCIAL} {instance.codigo}: activo={valor}.',
        )
        return Response(self.get_serializer(instance).data)


class CartaViewSet(BaseViewSet, viewsets.ModelViewSet):
    queryset = Carta.objects.all()
    serializer_class = CartaSerializer
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ROLES_VALIDOS,
        'update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'partial_update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'estado': ROLES_VALIDOS,
        'disponibilidad': ROLES_GESTORES,
    }
    http_method_names = ('get', 'post', 'put', 'patch', 'head', 'options')

    def get_queryset(self):
        queryset = filtrar_delegaciones(
            Carta.objects.select_related('responsable', 'vecino').defer(
                'contenido', 'respuesta', 'vecino__telefono', 'vecino__correo', 'vecino__direccion',
            ),
            self.request.user,
        )
        if rol_usuario(self.request.user) in ('funcionario', 'verificador'):
            queryset = queryset.filter(Q(responsable=self.request.user) | Q(creado_por=self.request.user))
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        registrar_auditoria(self.request, 'crear_carta', instance, f'Carta {instance.codigo} creada.')

    def perform_update(self, serializer):
        instance = self.get_object()
        if not _puede_editar(self.request.user, instance):
            raise PermissionDenied('No puede editar esta carta.')
        if instance.estado == Carta.Estado.CERRADA:
            raise ValidationError('No se puede editar una carta cerrada.')
        instance = serializer.save()
        registrar_auditoria(self.request, 'actualizar_carta', instance, f'Carta {instance.codigo} actualizada.')

    def destroy(self, request, *args, **kwargs):
        raise PermissionDenied('Las cartas no se eliminan físicamente; solicite su desactivación.')

    @action(detail=True, methods=('post',), url_path='estado')
    def estado(self, request, pk=None):
        instance = self.get_object()
        _validar_edicion(request.user, instance)
        nuevo = request.data.get('estado')
        transiciones = {
            Carta.Estado.INGRESADA: {Carta.Estado.ASIGNADA, Carta.Estado.EN_PROCESO},
            Carta.Estado.ASIGNADA: {Carta.Estado.EN_PROCESO},
            Carta.Estado.EN_PROCESO: {Carta.Estado.RESPONDIDA},
            Carta.Estado.RESPONDIDA: {Carta.Estado.CERRADA, Carta.Estado.EN_PROCESO},
            Carta.Estado.CERRADA: set(),
        }
        _validar_transicion_estado(instance, nuevo, transiciones)
        anterior = instance.estado
        instance.estado = nuevo
        if nuevo == Carta.Estado.RESPONDIDA:
            respuesta = (request.data.get('respuesta') or '').strip()
            if not respuesta:
                raise ValidationError({'respuesta': 'Ingrese la respuesta de la carta.'})
            instance.respuesta = respuesta
            instance.fecha_respuesta = timezone.localdate()
        if nuevo == Carta.Estado.EN_PROCESO:
            instance.fecha_respuesta = None
        instance.save()
        registrar_auditoria(
            request, 'cambiar_estado_carta', instance,
            f'Carta {instance.codigo}: {anterior} → {nuevo}.',
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=('post',), url_path='disponibilidad')
    def disponibilidad(self, request, pk=None):
        instance = self.get_object()
        if rol_usuario(request.user) not in ROLES_GESTORES:
            raise PermissionDenied('Solo un gestor puede desactivar una carta.')
        valor = request.data.get('activo')
        if not isinstance(valor, bool):
            raise ValidationError({'activo': MENSAJE_BOOLEANO_INVALIDO})
        instance.activo = valor
        instance.save(update_fields=['activo', 'actualizado_en'])
        registrar_auditoria(request, 'cambiar_disponibilidad_carta', instance,
                            f'Carta {instance.codigo}: activa={valor}.')
        return Response(self.get_serializer(instance).data)


class HitoViewSet(BaseViewSet, viewsets.ModelViewSet):
    queryset = Hito.objects.all()
    serializer_class = HitoSerializer
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'create': ('administrador', 'delegado'),
        'update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'partial_update': (*ROLES_GESTORES, 'funcionario', 'verificador'),
        'estado': ROLES_VALIDOS,
        'disponibilidad': ROLES_GESTORES,
    }
    http_method_names = ('get', 'post', 'put', 'patch', 'head', 'options')

    def get_queryset(self):
        queryset = Hito.objects.filter(filtro_hito_delegacion(self.request.user)).select_related(
            'responsable',
        ).annotate(
            delegacion_id_api=Coalesce(
                'actividad__delegacion_id',
                'gestion_social__delegacion_id',
                'compromiso__delegacion_id',
            ),
        )
        if rol_usuario(self.request.user) in ('funcionario', 'verificador'):
            queryset = queryset.filter(Q(responsable=self.request.user) | Q(creado_por=self.request.user))
        return queryset

    def perform_create(self, serializer):
        instance = serializer.save()
        registrar_auditoria(self.request, 'crear_hito', instance, f'Hito {instance.codigo} creado.')

    def perform_update(self, serializer):
        instance = self.get_object()
        if rol_usuario(self.request.user) not in ROLES_GESTORES:
            raise PermissionDenied('No puede editar este hito.')
        if instance.estado in (Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO):
            raise ValidationError('No se puede editar un hito finalizado.')
        instance = serializer.save()
        registrar_auditoria(self.request, 'actualizar_hito', instance, f'Hito {instance.codigo} actualizado.')

    def destroy(self, request, *args, **kwargs):
        raise PermissionDenied('Los hitos no se eliminan físicamente; solicite su desactivación.')

    @action(detail=True, methods=('post',), url_path='estado')
    def estado(self, request, pk=None):
        instance = self.get_object()
        _validar_edicion(request.user, instance)
        nuevo = request.data.get('estado')
        transiciones = {
            Hito.Estado.PENDIENTE: {Hito.Estado.EN_PROCESO, Hito.Estado.CANCELADO},
            Hito.Estado.EN_PROCESO: {Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO},
            Hito.Estado.COMPLETADO: set(),
            Hito.Estado.CANCELADO: set(),
        }
        _validar_transicion_estado(instance, nuevo, transiciones)
        anterior = instance.estado
        instance.estado = nuevo
        if nuevo == Hito.Estado.COMPLETADO:
            instance.fecha_completada = timezone.localdate()
        if nuevo == Hito.Estado.CANCELADO:
            instance.motivo_cambio = (request.data.get('motivo') or '').strip()
            if not instance.motivo_cambio:
                raise ValidationError({'motivo': 'Indique la razón de cancelación.'})
        instance.save()
        registrar_auditoria(
            request, 'cambiar_estado_hito', instance,
            f'Hito {instance.codigo}: {anterior} → {nuevo}.',
        )
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=('post',), url_path='disponibilidad')
    def disponibilidad(self, request, pk=None):
        instance = self.get_object()
        if rol_usuario(request.user) not in ROLES_GESTORES:
            raise PermissionDenied('Solo un gestor puede desactivar un hito.')
        valor = request.data.get('activo')
        if not isinstance(valor, bool):
            raise ValidationError({'activo': MENSAJE_BOOLEANO_INVALIDO})
        instance.activo = valor
        instance.save(update_fields=['activo', 'actualizado_en'])
        registrar_auditoria(request, 'cambiar_disponibilidad_hito', instance,
                            f'Hito {instance.codigo}: activo={valor}.')
        return Response(self.get_serializer(instance).data)


class AporteViewSet(ReadOnlyViewSet):
    serializer_class = AporteSerializer
    queryset = AporteIndicador.objects.all()
    roles_por_accion = {
        'list': ROLES_VALIDOS,
        'retrieve': ROLES_VALIDOS,
        'proponer': ROLES_VALIDOS,
        'validar': ('administrador', 'delegado', 'verificador'),
    }

    def get_queryset(self):
        _seleccionar_delegacion(self.request)
        queryset = aportes_visibles(self.request).select_related(None).select_related(
            'indicador__meta__delegacion', 'validado_por',
        ).defer('comentario')
        if rol_usuario(self.request.user) == 'funcionario':
            queryset = queryset.filter(actividad__responsable=self.request.user)
        return queryset

    @action(detail=False, methods=('post',), url_path='proponer')
    def proponer(self, request):
        _seleccionar_delegacion(request)
        serializer = ProponerAporteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        datos = serializer.validated_data
        if not queryset_atenciones(request).filter(pk=datos['actividad'].pk).exists():
            raise NotFound()
        indicador = datos['indicador']
        if not filtrar_delegaciones(
            Indicador.objects.filter(pk=indicador.pk), request.user, 'meta__delegacion',
        ).exists():
            raise NotFound()
        try:
            aporte = proponer_aporte(
                request,
                datos['actividad'],
                indicador,
                datos.get('valor_declarado'),
                datos['version'],
            )
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(AporteSerializer(aporte, context=self.get_serializer_context()).data)

    @action(detail=True, methods=('post',), url_path='validar')
    def validar(self, request, pk=None):
        aporte = self.get_object()
        if not pendientes_validacion(request).filter(pk=aporte.pk).exists():
            raise PermissionDenied('No puede revisar este aporte o ya fue revisado.')
        serializer = ValidarAporteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            updated = validar_aporte(request, aporte.pk, **serializer.validated_data)
        except DjangoValidationError as error:
            raise ValidationError(error.messages) from error
        return Response(AporteSerializer(updated, context=self.get_serializer_context()).data)


class AuditoriaViewSet(ReadOnlyViewSet):
    serializer_class = AuditoriaSerializer
    queryset = RegistroAuditoria.objects.all()
    roles_por_accion = {'list': ('administrador',), 'retrieve': ('administrador',)}

    def get_queryset(self):
        return RegistroAuditoria.objects.select_related('usuario').order_by('-timestamp')


def _validar_transicion_estado(instance, nuevo, transiciones):
    if nuevo not in transiciones.get(instance.estado, set()):
        raise ValidationError({'estado': MENSAJE_TRANSICION_INVALIDA})


TIPOS_TUBO = ('actividad', 'compromiso', 'gestion_social', 'carta')


def _filtrar_delegacion_tubo(delegaciones, delegacion_id):
    if not delegacion_id:
        return delegaciones
    try:
        delegacion_id = int(delegacion_id)
    except ValueError as error:
        raise ValidationError({'delegacion': 'Seleccione una delegación válida.'}) from error
    delegaciones = delegaciones.filter(pk=delegacion_id)
    if not delegaciones.exists():
        raise NotFound()
    return delegaciones


def _agregar_actividades_tubo(registros, delegaciones, desde, hasta):
    actividades = AtencionCiudadana.objects.filter(
        va_al_tubo=True, activo=True, delegacion__in=delegaciones,
    ).select_related('responsable').annotate(
        plazo_tubo=Min('compromisos__fecha_hora'),
    ).only(
        'id', 'titulo', 'fecha', 'estado', 'delegacion_id',
        'responsable__id', 'responsable__first_name', 'responsable__last_name',
    )
    for item in _filtrar_fecha(actividades, 'fecha', desde, hasta):
        plazo = timezone.localtime(item.plazo_tubo).date() if item.plazo_tubo else None
        registros.append(_registro_tubo(
            'actividad', f'ACT-{item.pk:06d}', item.pk, item.titulo, item.estado,
            item.fecha, plazo, item.delegacion_id, item.responsable,
        ))


def _agregar_compromisos_tubo(registros, delegaciones, desde, hasta):
    compromisos = Compromiso.objects.filter(delegacion__in=delegaciones).exclude(
        actividades__va_al_tubo=True, actividades__activo=True,
    ).select_related(
        'responsable',
    ).only(
        'id', 'fecha_hora', 'titulo', 'estado', 'delegacion_id',
        'responsable__id', 'responsable__first_name', 'responsable__last_name',
    )
    for item in _filtrar_fecha(compromisos, 'fecha_hora__date', desde, hasta):
        registros.append(_registro_tubo(
            'compromiso', item.codigo, item.pk, item.titulo, item.estado,
            item.fecha_hora.date(), item.fecha_hora.date(), item.delegacion_id, item.responsable,
        ))


def _agregar_gestiones_tubo(registros, delegaciones, desde, hasta):
    gestiones = GestionSocial.objects.filter(
        ingresa_al_tubo=True, activo=True, delegacion__in=delegaciones,
    ).select_related('responsable').only(
        'id', 'codigo', 'titulo', 'estado', 'fecha_ingreso', 'fecha_compromiso',
        'delegacion_id', 'responsable__id', 'responsable__first_name', 'responsable__last_name',
    )
    for item in _filtrar_fecha(gestiones, 'fecha_ingreso', desde, hasta):
        registros.append(_registro_tubo(
            'gestion_social', item.codigo, item.pk, item.titulo, item.estado,
            item.fecha_ingreso, item.fecha_compromiso, item.delegacion_id, item.responsable,
        ))


def _agregar_cartas_tubo(registros, delegaciones, desde, hasta):
    cartas = Carta.objects.filter(
        ingresa_al_tubo=True, activo=True, delegacion__in=delegaciones,
    ).select_related('responsable').only(
        'id', 'codigo', 'asunto', 'estado', 'fecha_ingreso', 'fecha_compromiso',
        'delegacion_id', 'responsable__id', 'responsable__first_name', 'responsable__last_name',
    )
    for item in _filtrar_fecha(cartas, 'fecha_ingreso', desde, hasta):
        registros.append(_registro_tubo(
            'carta', item.codigo, item.pk, item.asunto, item.estado,
            item.fecha_ingreso, item.fecha_compromiso, item.delegacion_id, item.responsable,
        ))


def _construir_registros_tubo(filtro_tipo, delegaciones, desde, hasta):
    agregadores = {
        'actividad': _agregar_actividades_tubo,
        'compromiso': _agregar_compromisos_tubo,
        'gestion_social': _agregar_gestiones_tubo,
        'carta': _agregar_cartas_tubo,
    }
    registros = []
    for tipo, agregar in agregadores.items():
        if filtro_tipo in (None, tipo):
            agregar(registros, delegaciones, desde, hasta)
    return registros


def _filtrar_registros_tubo(registros, estado, busqueda):
    if estado:
        registros = [item for item in registros if item['estado'] == estado]
    if busqueda:
        consulta = busqueda.casefold()
        registros = [
            item for item in registros
            if consulta in item['codigo'].casefold() or consulta in item['titulo'].casefold()
        ]
    return registros


class TuboView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        delegaciones = delegaciones_autorizadas(request.user)
        if rol_usuario(request.user) not in ROLES_VALIDOS or not delegaciones.exists():
            return Response({'count': 0, 'results': []})
        delegaciones = _filtrar_delegacion_tubo(
            delegaciones, request.query_params.get('delegacion'),
        )
        filtro_tipo = request.query_params.get('tipo')
        if filtro_tipo not in (None, *TIPOS_TUBO):
            raise ValidationError({'tipo': 'Tipo de registro no válido.'})
        estado = request.query_params.get('estado')
        busqueda = (request.query_params.get('q') or '').strip()
        fecha_desde, fecha_hasta = _rango_fechas(
            request.query_params.get('desde'),
            request.query_params.get('hasta'),
        )
        if len(busqueda) > 100:
            raise ValidationError({'q': 'La búsqueda no puede superar 100 caracteres.'})
        registros = _construir_registros_tubo(
            filtro_tipo, delegaciones, fecha_desde, fecha_hasta,
        )
        registros = _filtrar_registros_tubo(registros, estado, busqueda)
        registros.sort(key=lambda item: (item['fecha'], item['codigo']), reverse=True)
        page = self.paginate_queryset(registros)
        return self.get_paginated_response(page)

    @property
    def paginator(self):
        from rest_framework.pagination import PageNumberPagination
        if not hasattr(self, '_paginator'):
            self._paginator = PageNumberPagination()
            self._paginator.page_size = 50
        return self._paginator

    def paginate_queryset(self, queryset):
        return self.paginator.paginate_queryset(queryset, self.request, view=self)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


class DashboardView(APIView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        _seleccionar_delegacion(request)
        contexto = construir_dashboard(request)
        periodo = contexto.get('periodo')
        filas = [
            {
                'meta_id': fila.meta.pk,
                'meta': fila.meta.nombre,
                'delegacion': fila.meta.delegacion.nombre,
                'cumplimiento': fila.resultado.cumplimiento_normalizado,
                'semaforo': fila.semaforo.estado,
                'semaforo_texto': fila.semaforo.texto,
                'configuracion_completa': fila.resultado.configuracion_completa,
            }
            for fila in contexto.get('filas', [])
        ]
        return Response({
            'fecha_corte': contexto['fecha_corte'],
            'periodo': (
                {'id': periodo.pk, 'nombre': periodo.nombre,
                 'fecha_inicio': periodo.fecha_inicio, 'fecha_fin': periodo.fecha_fin}
                if periodo else None
            ),
            'mensaje': contexto['mensaje'],
            'avance_esperado': contexto['esperado'],
            'conteos': contexto['conteos'],
            'total_metas': contexto['total_metas'],
            'metas_calculables': contexto['metas_calculables'],
            'metas_incompletas': contexto['metas_incompletas'],
            'metas': filas,
        })


def _seleccionar_delegacion(request):
    solicitada = (
        request.query_params.get('delegacion')
        or request.data.get('delegacion')
    )
    if solicitada in (None, ''):
        return
    try:
        pk = int(solicitada)
    except (TypeError, ValueError) as error:
        raise ValidationError({'delegacion': 'Seleccione una delegación válida.'}) from error
    if not delegaciones_autorizadas(request.user).filter(pk=pk).exists():
        raise ValidationError({'delegacion': 'No tiene acceso a esa delegación.'})
    request.session[DELEGACION_SESION] = pk
    if hasattr(request, '_contexto_territorial_cache'):
        del request._contexto_territorial_cache


def _filtrar_fecha(queryset, field, desde, hasta):
    if desde:
        queryset = queryset.filter(**{f'{field}__gte': desde})
    if hasta:
        queryset = queryset.filter(**{f'{field}__lte': hasta})
    return queryset


def _rango_fechas(desde, hasta):
    try:
        desde = datetime.strptime(desde, '%Y-%m-%d').date() if desde else None
        hasta = datetime.strptime(hasta, '%Y-%m-%d').date() if hasta else None
    except ValueError as error:
        raise ValidationError({'fecha': 'Use fechas con formato AAAA-MM-DD.'}) from error
    if desde and hasta and desde > hasta:
        raise ValidationError({'fecha': 'La fecha inicial debe ser anterior a la fecha final.'})
    return desde, hasta


def _registro_tubo(tipo, codigo, pk, titulo, estado, fecha, fecha_compromiso, delegacion_id, responsable):
    return {
        'tipo': tipo,
        'id': pk,
        'codigo': codigo,
        'titulo': titulo,
        'estado': estado,
        'fecha': fecha,
        'fecha_compromiso': fecha_compromiso,
        'delegacion': delegacion_id,
        'responsable': {'id': responsable.pk, 'nombre': etiqueta_usuario(responsable)},
    }


def _puede_editar(user, objeto):
    if rol_usuario(user) in ROLES_GESTORES:
        return True
    return getattr(objeto, 'responsable_id', None) == user.pk


def _validar_edicion(user, objeto):
    if not _puede_editar(user, objeto):
        raise PermissionDenied('No puede actualizar este registro.')
