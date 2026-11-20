"""Datos de entrada documentados para los flujos principales de la API."""
from rest_framework import serializers


class TipoEntradaSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=30)
    nombre = serializers.CharField(max_length=150)
    descripcion = serializers.CharField(required=False, allow_blank=True)
    activo = serializers.BooleanField(required=False, default=True)
    delegacion = serializers.IntegerField(required=False, allow_null=True, help_text='Solo administrador global; omitir para alcance general.')


class SubAtencionEntradaSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=150)
    tipo = serializers.IntegerField(help_text='Identificador del tipo de atención.')
    activo = serializers.BooleanField(required=False, default=True)
    delegacion = serializers.IntegerField(required=False, allow_null=True, help_text='Solo administrador global; omitir para alcance general.')


class ActividadEntradaSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=200)
    fecha = serializers.DateField()
    solicitante = serializers.CharField(max_length=180)
    tipo = serializers.IntegerField()
    subatencion = serializers.IntegerField()
    descripcion = serializers.CharField()
    delegacion = serializers.IntegerField(required=False, help_text='Delegación activa, obligatoria para administrador global.')
    territorio = serializers.IntegerField(required=False, allow_null=True)
    origen = serializers.CharField(required=False, allow_blank=True)
    va_al_tubo = serializers.BooleanField(required=False)
    plazo_tubo = serializers.DateTimeField(required=False, allow_null=True)
    indicador = serializers.IntegerField(required=False, allow_null=True)
    valor_declarado = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class ActividadEditarSerializer(serializers.Serializer):
    titulo = serializers.CharField(max_length=200)
    fecha = serializers.DateField()
    solicitante = serializers.CharField(max_length=180)
    territorio = serializers.IntegerField(required=False, allow_null=True)
    descripcion = serializers.CharField()


class RecuperacionEntradaSerializer(serializers.Serializer):
    identificador = serializers.CharField(max_length=254, help_text='Nombre de usuario o correo.')
