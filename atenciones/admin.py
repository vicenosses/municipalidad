from django.contrib import admin

from atenciones.models import AtencionCiudadana


@admin.register(AtencionCiudadana)
class AtencionCiudadanaAdmin(admin.ModelAdmin):
    list_display = ('solicitante', 'tipo', 'subatencion', 'delegacion', 'responsable', 'fecha_registro')
    list_filter = ('tipo', 'delegacion')
    search_fields = ('solicitante', 'descripcion')
