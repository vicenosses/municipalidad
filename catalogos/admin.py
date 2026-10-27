from django.contrib import admin

from catalogos.models import ItemMeta, SubAtencion, TipoAtencion


@admin.register(ItemMeta)
class ItemMetaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo')
    search_fields = ('codigo', 'nombre')


@admin.register(TipoAtencion)
class TipoAtencionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'es_general', 'delegacion', 'activo')
    search_fields = ('codigo', 'nombre')

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubAtencion)
class SubAtencionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'tipo', 'es_general', 'delegacion', 'activo')
    list_filter = ('tipo', 'es_general', 'delegacion', 'activo')
    search_fields = ('codigo', 'nombre')
    readonly_fields = ('codigo',)

    def has_delete_permission(self, request, obj=None):
        return False
