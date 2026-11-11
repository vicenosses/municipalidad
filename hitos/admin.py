from django.contrib import admin

# Register your models here.
from django.contrib import admin

from hitos.models import Hito


@admin.register(Hito)
class HitoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'titulo', 'estado', 'fecha_programada', 'responsable', 'activo')
    list_filter = ('estado', 'activo')
    search_fields = ('codigo', 'titulo')
