from django.contrib import admin

# Register your models here.
from django.contrib import admin

from cartas.models import Carta


@admin.register(Carta)
class CartaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'asunto', 'estado', 'delegacion', 'responsable', 'fecha_ingreso', 'activo')
    list_filter = ('estado', 'delegacion', 'activo')
    search_fields = ('codigo', 'asunto', 'vecino__rut', 'vecino__nombres', 'vecino__apellidos')
