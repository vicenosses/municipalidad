from django.contrib import admin

# Register your models here.
from django.contrib import admin

from gestion_social.models import GestionSocial


@admin.register(GestionSocial)
class GestionSocialAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'titulo', 'tipo', 'estado', 'delegacion', 'responsable', 'activo')
    list_filter = ('estado', 'tipo', 'delegacion', 'activo')
    search_fields = ('codigo', 'titulo', 'vecino__rut', 'vecino__nombres', 'vecino__apellidos')
