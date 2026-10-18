from django.contrib import admin

from catalogos.models import ItemMeta, SubAtencion, TipoAtencion


@admin.register(ItemMeta)
class ItemMetaAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo')
    search_fields = ('codigo', 'nombre')


@admin.register(TipoAtencion)
class TipoAtencionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo')
    search_fields = ('codigo', 'nombre')


@admin.register(SubAtencion)
class SubAtencionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'tipo', 'activo')
    list_filter = ('tipo', 'activo')
    search_fields = ('codigo', 'nombre')
