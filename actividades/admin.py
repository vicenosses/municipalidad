from django.contrib import admin

from actividades.models import Actividad


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'fecha', 'funcionario', 'delegacion', 'estado')
    list_filter = ('estado', 'delegacion', 'fecha')
    search_fields = ('titulo', 'descripcion')
