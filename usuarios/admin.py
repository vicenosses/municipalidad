from django.contrib import admin

from usuarios.models import CodigoRecuperacion, Delegacion, Perfil, Rol


@admin.register(Delegacion)
class DelegacionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'comuna', 'activa')
    search_fields = ('codigo', 'nombre', 'comuna')


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'alcance', 'activo')
    search_fields = ('codigo', 'nombre')


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'rol', 'delegacion', 'activo')
    list_filter = ('rol', 'delegacion', 'activo')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name', 'usuario__email')
    filter_horizontal = ('delegaciones',)


@admin.register(CodigoRecuperacion)
class CodigoRecuperacionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'creado', 'expira', 'intentos', 'usado')
    readonly_fields = ('usuario', 'codigo_hash', 'creado', 'expira', 'intentos', 'usado')
