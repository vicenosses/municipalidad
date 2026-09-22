from django.contrib import admin

from usuarios.models import Delegacion, Perfil


@admin.register(Delegacion)
class DelegacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'activa')
    search_fields = ('nombre',)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'rol', 'delegacion', 'activo')
    list_filter = ('rol', 'delegacion', 'activo')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name')
