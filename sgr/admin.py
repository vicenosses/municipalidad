from django.contrib import admin
from django import forms

from sgr.models import Indicador, Meta, Periodo


@admin.register(Periodo)
class PeriodoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'fecha_inicio', 'fecha_fin', 'activo', 'creado_por')
    list_filter = ('activo',)
    search_fields = ('nombre',)
    readonly_fields = ('creado_por', 'creado_en', 'actualizado_en')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Meta)
class MetaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'periodo', 'delegacion', 'activo')
    list_filter = ('periodo', 'delegacion', 'activo')
    search_fields = ('nombre', 'descripcion')
    readonly_fields = ('creado_por', 'creado_en', 'actualizado_en')

    def get_readonly_fields(self, request, obj=None):
        campos = super().get_readonly_fields(request, obj)
        return (*campos, 'periodo', 'delegacion') if obj else campos

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.periodo.activo)

    def has_delete_permission(self, request, obj=None):
        return False


class IndicadorAdminForm(forms.ModelForm):
    motivo_ponderacion = forms.CharField(label='Motivo del cambio de ponderación', required=False)
    motivo_objetivo = forms.CharField(label='Motivo del cambio de objetivo', required=False)

    class Meta:
        model = Indicador
        fields = '__all__'

    def clean(self):
        datos = super().clean()
        self.instance._motivo_objetivo = datos.get('motivo_objetivo', '')
        self.instance._motivo_ponderacion = datos.get('motivo_ponderacion', '')
        return datos


@admin.register(Indicador)
class IndicadorAdmin(admin.ModelAdmin):
    form = IndicadorAdminForm
    list_display = ('nombre', 'meta', 'unidad_medida', 'valor_objetivo', 'ponderacion', 'sentido', 'activo')
    list_filter = ('meta__periodo', 'meta__delegacion', 'unidad_medida', 'activo')
    list_select_related = ('meta__periodo',)
    search_fields = ('nombre', 'descripcion', 'meta__nombre')
    readonly_fields = ('creado_por', 'creado_en', 'actualizado_en')

    def get_readonly_fields(self, request, obj=None):
        campos = super().get_readonly_fields(request, obj)
        return (*campos, 'meta') if obj else campos

    def save_model(self, request, obj, form, change):
        obj._actor_objetivo = request.user
        obj._request_objetivo = request
        obj._actor_ponderacion = request.user
        obj._request_ponderacion = request
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None or (obj.meta.activo and obj.meta.periodo.activo)
        )

    def has_delete_permission(self, request, obj=None):
        return False
