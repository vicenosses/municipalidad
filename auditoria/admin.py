from django.contrib import admin

from auditoria.models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'usuario', 'accion', 'modelo', 'ip')
    list_filter = ('accion', 'modelo', 'timestamp')
    search_fields = ('descripcion', 'usuario__username', 'objeto_id')
    readonly_fields = (
        'usuario',
        'accion',
        'modelo',
        'objeto_id',
        'descripcion',
        'ip',
        'timestamp',
    )
