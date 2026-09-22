from django.contrib import admin

from evidencias.models import Evidencia


@admin.register(Evidencia)
class EvidenciaAdmin(admin.ModelAdmin):
    list_display = ('codigo_respaldo', 'actividad', 'estado', 'subido_por', 'fecha_subida')
    list_filter = ('estado', 'fecha_subida')
    search_fields = ('codigo_respaldo', 'actividad__titulo')
    readonly_fields = ('codigo_respaldo',)
