from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from cartas.models import Carta
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.forms import validar_archivo
from evidencias.models import Evidencia
from gestion_social.models import GestionSocial
from hitos.models import Hito
from sgr.models import AporteIndicador, AsignacionMeta, Indicador, Meta as SGRMeta, Periodo
from usuarios.mixins import obtener_rol
from usuarios.models import Cargo, Delegacion, Perfil, Rol, Territorio, Vecino
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa

from api.access import (
    ROLES_GESTORES,
    delegaciones_usuario,
    en_delegacion,
    etiqueta_usuario,
    rol_usuario,
    rut_enmascarado,
    usuario_puede_ver_detalle,
)

User = get_user_model()


class UsuarioResumenSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()
    rol = serializers.SerializerMethodField()
    cargo = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'nombre', 'rol', 'cargo')

    def get_nombre(self, obj):
        return etiqueta_usuario(obj)

    def get_rol(self, obj):
        return obtener_rol(obj)

    def get_cargo(self, obj):
        perfil = getattr(obj, 'perfil', None)
        return perfil.cargo if perfil else ''


class MiPerfilSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()
    rol = serializers.SerializerMethodField()
    cargo = serializers.SerializerMethodField()
    delegaciones = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'nombre', 'email', 'rol', 'cargo', 'delegaciones')

    def get_nombre(self, obj):
        return obj.get_full_name() or obj.username

    def get_rol(self, obj):
        return obtener_rol(obj)

    def get_cargo(self, obj):
        perfil = getattr(obj, 'perfil', None)
        return perfil.cargo if perfil else ''

    def get_delegaciones(self, obj):
        return list(delegaciones_autorizadas(obj).values('id', 'codigo', 'nombre'))


class DelegacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Delegacion
        fields = ('id', 'codigo', 'nombre', 'comuna', 'activa')


class TerritorioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Territorio
        fields = ('id', 'codigo', 'nombre', 'delegacion', 'activo')


class CargoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cargo
        fields = ('id', 'nombre', 'descripcion', 'alcance', 'activo')


class RolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = ('id', 'codigo', 'nombre', 'descripcion', 'alcance', 'activo')


class TipoAtencionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAtencion
        fields = ('id', 'codigo', 'nombre', 'descripcion', 'es_general', 'delegacion', 'activo')


class SubAtencionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubAtencion
        fields = ('id', 'codigo', 'nombre', 'tipo', 'es_general', 'delegacion', 'activo')


class VecinoResumenSerializer(serializers.ModelSerializer):
    nombre = serializers.SerializerMethodField()
    rut = serializers.SerializerMethodField()

    class Meta:
        model = Vecino
        fields = ('id', 'nombre', 'rut', 'territorio')

    def get_nombre(self, obj):
        nombre = (obj.nombres.split() or [''])[0]
        apellido = (obj.apellidos.split() or [''])[0]
        return f'{nombre} {apellido[0]}.' if apellido else nombre

    def get_rut(self, obj):
        return rut_enmascarado(obj.rut)


class AtencionSerializer(serializers.ModelSerializer):
    codigo = serializers.SerializerMethodField()
    responsable = UsuarioResumenSerializer(read_only=True)
    descripcion = serializers.SerializerMethodField()
    estado_evidencias = serializers.SerializerMethodField()

    class Meta:
        model = AtencionCiudadana
        fields = (
            'id', 'codigo', 'titulo', 'fecha', 'estado', 'activo', 'tipo', 'subatencion',
            'delegacion', 'territorio', 'responsable', 'va_al_tubo', 'descripcion',
            'estado_evidencias', 'fecha_registro',
        )
        read_only_fields = fields

    def get_codigo(self, obj):
        return f'ACT-{obj.pk:06d}'

    def get_descripcion(self, obj):
        if self.context.get('view') and self.context['view'].action == 'list':
            return None
        return obj.descripcion if usuario_puede_ver_detalle(self.context['request'].user, obj) else None

    def get_estado_evidencias(self, obj):
        if 'evidencias' in obj._prefetched_objects_cache:
            evidencias = [
                (evidencia.pk, evidencia.estado, evidencia.reemplaza_id)
                for evidencia in obj._prefetched_objects_cache['evidencias']
            ]
        else:
            evidencias = list(obj.evidencias.values_list('pk', 'estado', 'reemplaza_id'))
        reemplazadas = {reemplaza_id for _, _, reemplaza_id in evidencias if reemplaza_id}
        estados = {estado for pk, estado, _ in evidencias if pk not in reemplazadas}
        if not estados:
            return 'sin_evidencia'
        if 'rechazada' in estados:
            return 'rechazada'
        if 'pendiente' in estados:
            return 'pendiente'
        return 'aprobada'


class CompromisoSerializer(serializers.ModelSerializer):
    codigo = serializers.CharField(read_only=True)
    responsable = UsuarioResumenSerializer(read_only=True)
    descripcion = serializers.SerializerMethodField()
    solicitante = serializers.SerializerMethodField()

    class Meta:
        model = Compromiso
        fields = (
            'id', 'codigo', 'titulo', 'estado', 'fecha_hora', 'fecha_realizacion', 'delegacion',
            'responsable', 'actividades', 'descripcion', 'solicitante', 'esta_vencido',
            'proximo_a_vencer', 'realizado_fuera_de_plazo', 'creado',
        )
        read_only_fields = fields

    def get_descripcion(self, obj):
        if self.context.get('view') and self.context['view'].action == 'list':
            return None
        return obj.descripcion if usuario_puede_ver_detalle(self.context['request'].user, obj) else None

    def get_solicitante(self, obj):
        view = self.context.get('view')
        if view and view.action == 'list':
            return None
        if not usuario_puede_ver_detalle(self.context['request'].user, obj):
            return None
        return obj.solicitante


class GestionSocialSerializer(serializers.ModelSerializer):
    vecino = serializers.PrimaryKeyRelatedField(
        queryset=Vecino.objects.all(), required=False, allow_null=True, write_only=True,
    )
    vecino_resumen = VecinoResumenSerializer(source='vecino', read_only=True)
    responsable = UsuarioResumenSerializer(read_only=True)
    responsable_id = serializers.PrimaryKeyRelatedField(
        source='responsable', queryset=User.objects.filter(is_active=True),
        required=False, write_only=True,
    )
    descripcion = serializers.CharField(write_only=True)

    class Meta:
        model = GestionSocial
        fields = (
            'id', 'codigo', 'titulo', 'tipo', 'estado', 'delegacion', 'territorio',
            'vecino', 'vecino_resumen', 'responsable', 'responsable_id', 'fecha_ingreso',
            'fecha_compromiso', 'ingresa_al_tubo', 'activo', 'descripcion',
            'creado_en', 'actualizado_en',
        )
        read_only_fields = ('id', 'codigo', 'estado', 'activo', 'creado_en', 'actualizado_en')
        extra_kwargs = {'delegacion': {'required': False}}

    def validate(self, attrs):
        return _validar_alcance_registro(self, attrs)

    def create(self, validated_data):
        validated_data['creado_por'] = self.context['request'].user
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        view = self.context.get('view')
        if request and view and view.action != 'list' and usuario_puede_ver_detalle(request.user, instance):
            data['descripcion'] = instance.descripcion
        return data


class CartaSerializer(serializers.ModelSerializer):
    vecino = serializers.PrimaryKeyRelatedField(
        queryset=Vecino.objects.all(), required=False, allow_null=True, write_only=True,
    )
    vecino_resumen = VecinoResumenSerializer(source='vecino', read_only=True)
    responsable = UsuarioResumenSerializer(read_only=True)
    responsable_id = serializers.PrimaryKeyRelatedField(
        source='responsable', queryset=User.objects.filter(is_active=True),
        required=False, write_only=True,
    )
    contenido = serializers.CharField(write_only=True)
    respuesta = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Carta
        fields = (
            'id', 'codigo', 'asunto', 'estado', 'delegacion', 'territorio', 'vecino',
            'vecino_resumen', 'responsable', 'responsable_id', 'fecha_ingreso',
            'fecha_compromiso', 'fecha_respuesta', 'ingresa_al_tubo', 'activo',
            'contenido', 'respuesta', 'creado_en', 'actualizado_en',
        )
        read_only_fields = (
            'id', 'codigo', 'estado', 'fecha_respuesta', 'activo', 'creado_en', 'actualizado_en',
        )
        extra_kwargs = {'delegacion': {'required': False}}

    def validate(self, attrs):
        return _validar_alcance_registro(self, attrs)

    def create(self, validated_data):
        validated_data['creado_por'] = self.context['request'].user
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        view = self.context.get('view')
        if request and view and view.action != 'list' and usuario_puede_ver_detalle(request.user, instance):
            data['contenido'] = instance.contenido
            data['respuesta'] = instance.respuesta
        return data


class HitoSerializer(serializers.ModelSerializer):
    actividad = serializers.PrimaryKeyRelatedField(
        queryset=AtencionCiudadana.objects.all(), required=False, allow_null=True,
    )
    gestion_social = serializers.PrimaryKeyRelatedField(
        queryset=GestionSocial.objects.all(), required=False, allow_null=True,
    )
    compromiso = serializers.PrimaryKeyRelatedField(
        queryset=Compromiso.objects.all(), required=False, allow_null=True,
    )
    responsable = UsuarioResumenSerializer(read_only=True)
    responsable_id = serializers.PrimaryKeyRelatedField(
        source='responsable', queryset=User.objects.filter(is_active=True),
        required=False, write_only=True,
    )
    descripcion = serializers.CharField(required=False, allow_blank=True, write_only=True)
    delegacion = serializers.SerializerMethodField()

    class Meta:
        model = Hito
        fields = (
            'id', 'codigo', 'titulo', 'descripcion', 'actividad', 'gestion_social',
            'compromiso', 'delegacion', 'responsable', 'responsable_id', 'fecha_programada',
            'fecha_completada', 'estado', 'motivo_cambio', 'activo', 'creado_en', 'actualizado_en',
        )
        read_only_fields = (
            'id', 'codigo', 'delegacion', 'fecha_completada', 'estado', 'activo',
            'creado_en', 'actualizado_en',
        )

    def get_delegacion(self, obj):
        if hasattr(obj, 'delegacion_id_api'):
            return obj.delegacion_id_api
        return obj.delegacion_id

    def validate(self, attrs):
        parent_fields = ('actividad', 'gestion_social', 'compromiso')
        parent = next((attrs.get(field) for field in parent_fields if attrs.get(field)), None)
        if self.instance and parent is None:
            parent = next((getattr(self.instance, field) for field in parent_fields if getattr(self.instance, f'{field}_id')), None)
        if parent is None:
            raise serializers.ValidationError('Vincule el hito a una actividad, gestión social o compromiso.')
        delegacion = parent.delegacion
        request = self.context['request']
        if not en_delegacion(request.user, delegacion):
            raise serializers.ValidationError('El registro relacionado está fuera de sus delegaciones autorizadas.')
        responsable = attrs.get('responsable', self.instance.responsable if self.instance else request.user)
        _validar_responsable(request.user, responsable, delegacion)
        attrs.setdefault('responsable', responsable)
        if rol_usuario(request.user) not in ROLES_GESTORES and not self.instance:
            attrs['responsable'] = request.user
        return attrs

    def create(self, validated_data):
        validated_data['creado_por'] = self.context['request'].user
        return super().create(validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        view = self.context.get('view')
        if request and view and view.action != 'list' and usuario_puede_ver_detalle(request.user, instance):
            data['descripcion'] = instance.descripcion
        return data


class PeriodoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Periodo
        fields = ('id', 'nombre', 'fecha_inicio', 'fecha_fin', 'activo')


class MetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = SGRMeta
        fields = ('id', 'periodo', 'delegacion', 'nombre', 'descripcion', 'activo')


class AsignacionMetaSerializer(serializers.ModelSerializer):
    funcionario = UsuarioResumenSerializer(read_only=True)

    class Meta:
        model = AsignacionMeta
        fields = ('id', 'meta', 'funcionario', 'cantidad_objetivo', 'ponderacion', 'observacion', 'activa')


class IndicadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Indicador
        fields = (
            'id', 'meta', 'nombre', 'descripcion', 'unidad_medida', 'unidad_personalizada',
            'sentido', 'valor_objetivo', 'ponderacion', 'activo',
        )


class AporteSerializer(serializers.ModelSerializer):
    actividad_codigo = serializers.SerializerMethodField()
    indicador_nombre = serializers.CharField(source='indicador.nombre', read_only=True)
    validado_por = UsuarioResumenSerializer(read_only=True)
    comentario = serializers.SerializerMethodField()

    class Meta:
        model = AporteIndicador
        fields = (
            'id', 'actividad', 'actividad_codigo', 'indicador', 'indicador_nombre', 'estado',
            'valor_declarado', 'valor_validado', 'comentario', 'validado_por', 'validado_en',
            'version', 'actualizado_en',
        )
        read_only_fields = fields

    def get_actividad_codigo(self, obj):
        return f'ACT-{obj.actividad_id:06d}'

    def get_comentario(self, obj):
        view = self.context.get('view')
        if view and view.action == 'list':
            return None
        if usuario_puede_ver_detalle(self.context['request'].user, obj.actividad):
            return obj.comentario
        return None


class ProponerAporteSerializer(serializers.Serializer):
    actividad = serializers.PrimaryKeyRelatedField(queryset=AtencionCiudadana.objects.all())
    indicador = serializers.PrimaryKeyRelatedField(queryset=Indicador.objects.all())
    valor_declarado = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True,
    )
    version = serializers.IntegerField(min_value=0, required=False, default=0)


class ValidarAporteSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    estado = serializers.ChoiceField(choices=AporteIndicador.Estado.choices)
    valor_validado = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True,
    )
    comentario = serializers.CharField(required=False, allow_blank=True)
    corregir_indicador = serializers.BooleanField(required=False, default=False)
    corregir_valor = serializers.BooleanField(required=False, default=False)
    corregir_evidencia = serializers.BooleanField(required=False, default=False)


class EvidenciaSerializer(serializers.ModelSerializer):
    archivo_url = serializers.SerializerMethodField()
    comentario_validacion = serializers.SerializerMethodField()

    class Meta:
        model = Evidencia
        fields = (
            'id', 'codigo_respaldo', 'identificador', 'atencion', 'compromiso',
            'descripcion', 'tipo_archivo', 'estado', 'subido_por', 'validado_por',
            'comentario_validacion', 'fecha_subida', 'fecha_validacion', 'archivo_url',
        )
        read_only_fields = fields

    def get_archivo_url(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        return request.build_absolute_uri(f'/api/v1/evidencias/{obj.pk}/archivo/')

    def get_comentario_validacion(self, obj):
        view = self.context.get('view')
        if view and view.action == 'list':
            return None
        parent = obj.atencion or obj.compromiso
        return obj.comentario_validacion if usuario_puede_ver_detalle(self.context['request'].user, parent) else None


class EvidenciaCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidencia
        fields = ('atencion', 'compromiso', 'descripcion', 'archivo')

    def validate_archivo(self, archivo):
        try:
            validar_archivo(archivo)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from error
        return archivo

    def validate(self, attrs):
        atencion = attrs.get('atencion')
        compromiso = attrs.get('compromiso')
        if bool(atencion) == bool(compromiso):
            raise serializers.ValidationError('Seleccione una actividad o un compromiso, pero no ambos.')
        from evidencias.permisos import puede_agregar_evidencia

        registro = atencion or compromiso
        if not puede_agregar_evidencia(self.context['request'], registro):
            raise serializers.ValidationError('No tiene permiso para agregar evidencia a este registro.')
        return attrs

    def create(self, validated_data):
        validated_data['subido_por'] = self.context['request'].user
        return super().create(validated_data)


class AuditoriaSerializer(serializers.ModelSerializer):
    usuario = UsuarioResumenSerializer(read_only=True)

    class Meta:
        model = RegistroAuditoria
        fields = ('id', 'usuario', 'accion', 'modelo', 'objeto_id', 'descripcion', 'timestamp')


def _validar_alcance_registro(serializer, attrs):
    request = serializer.context['request']
    user = request.user
    current = serializer.instance
    delegation = attrs.get('delegacion') or (current.delegacion if current else None)
    if delegation is None:
        delegation = get_delegacion_activa(request)
    if delegation is None or not en_delegacion(user, delegation):
        raise serializers.ValidationError({'delegacion': 'Seleccione una delegación autorizada.'})
    attrs['delegacion'] = delegation

    territory = attrs.get('territorio', current.territorio if current else None)
    if territory and territory.delegacion_id != delegation.pk:
        raise serializers.ValidationError({'territorio': 'El territorio debe pertenecer a la delegación.'})
    neighbor = attrs.get('vecino', current.vecino if current else None)
    if neighbor and neighbor.territorio.delegacion_id != delegation.pk:
        raise serializers.ValidationError({'vecino': 'El vecino debe pertenecer a la delegación.'})

    responsable = attrs.get('responsable', current.responsable if current else user)
    _validar_responsable(user, responsable, delegation)
    if rol_usuario(user) not in ROLES_GESTORES and responsable.pk != user.pk:
        raise serializers.ValidationError({'responsable_id': 'Solo un gestor puede asignar el registro a otra persona.'})
    attrs['responsable'] = responsable
    return attrs


def _validar_responsable(actor, responsable, delegation):
    if actor.is_superuser:
        return
    if responsable.pk == actor.pk and rol_usuario(actor) not in ROLES_GESTORES:
        return
    if not responsable.is_active or not Perfil.objects.filter(
        usuario=responsable,
        activo=True,
        delegaciones=delegation,
    ).exists():
        raise serializers.ValidationError({'responsable_id': 'La persona responsable debe estar activa y autorizada en la delegación.'})
