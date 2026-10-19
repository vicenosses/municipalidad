from django.contrib import admin

from agenda.models import Compromiso, HistorialCompromiso


@admin.register(Compromiso)
class CompromisoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'fecha_hora', 'responsable', 'delegacion', 'estado')
    list_filter = ('estado', 'delegacion')
    search_fields = ('titulo', 'descripcion', 'solicitante', 'area_apoyo')
    filter_horizontal = ('actividades',)


@admin.register(HistorialCompromiso)
class HistorialCompromisoAdmin(admin.ModelAdmin):
    list_display = ('compromiso', 'campo', 'realizado_por', 'creado')
    list_filter = ('campo', 'creado')
    search_fields = ('compromiso__titulo', 'valor_anterior', 'valor_nuevo', 'motivo')
    readonly_fields = (
        'compromiso',
        'campo',
        'valor_anterior',
        'valor_nuevo',
        'motivo',
        'realizado_por',
        'creado',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
