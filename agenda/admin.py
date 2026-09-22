from django.contrib import admin

from agenda.models import Compromiso


@admin.register(Compromiso)
class CompromisoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'fecha_hora', 'responsable', 'delegacion', 'estado')
    list_filter = ('estado', 'delegacion')
    search_fields = ('titulo', 'descripcion')
