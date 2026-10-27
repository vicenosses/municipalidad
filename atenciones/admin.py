from django.contrib import admin
from django.db import transaction

from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from atenciones.estados import registrar_creacion_actividad
from atenciones.permisos import queryset_atenciones


@admin.register(AtencionCiudadana)
class AtencionCiudadanaAdmin(admin.ModelAdmin):
    list_display = (
        'solicitante',
        'tipo',
        'subatencion',
        'delegacion',
        'responsable',
        'creado_por',
        'activo',
        'fecha_registro',
    )
    list_filter = ('tipo', 'delegacion', 'activo')
    search_fields = ('solicitante', 'descripcion')
    readonly_fields = ('creado_por', 'activo', 'estado')

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        if obj:
            readonly_fields = (*readonly_fields, 'delegacion')
            readonly_fields = (*readonly_fields, 'va_al_tubo')
            if not obj.activo:
                return tuple(
                    field.name
                    for field in obj._meta.fields
                    if not field.primary_key
                )
        return readonly_fields

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            original = AtencionCiudadana.objects.only(
                'delegacion_id',
                'creado_por_id',
            ).get(pk=obj.pk)
            obj.delegacion_id = original.delegacion_id
            obj.creado_por_id = original.creado_por_id
        elif obj.creado_por_id is None:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)
        if not change:
            registrar_creacion_actividad(obj, request.user)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HistorialEstadoActividad)
class HistorialEstadoActividadAdmin(admin.ModelAdmin):
    list_display = ('actividad', 'estado_anterior', 'estado_nuevo', 'actor', 'fecha_hora')
    list_select_related = ('actividad__tipo', 'actor')
    list_filter = ('estado_nuevo',)
    readonly_fields = ('actividad', 'estado_anterior', 'estado_nuevo', 'actor', 'fecha_hora', 'motivo')

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            actividad_id__in=queryset_atenciones(request).order_by().values('pk')
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
