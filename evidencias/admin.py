from django.contrib import admin
from django import forms

from evidencias.forms import validar_archivo
from evidencias.models import Evidencia


class EvidenciaAdminForm(forms.ModelForm):
    class Meta:
        model = Evidencia
        fields = '__all__'

    def clean_archivo(self):
        archivo = self.cleaned_data['archivo']
        if hasattr(archivo, 'content_type'):
            validar_archivo(archivo)
        return archivo


@admin.register(Evidencia)
class EvidenciaAdmin(admin.ModelAdmin):
    form = EvidenciaAdminForm
    list_display = (
        'identificador',
        'actividad',
        'atencion',
        'tipo_archivo',
        'estado',
        'subido_por',
        'fecha_subida',
    )
    list_filter = ('estado', 'fecha_subida')
    search_fields = ('identificador', 'codigo_respaldo', 'actividad__titulo', 'atencion__solicitante')
    readonly_fields = (
        'codigo_respaldo',
        'identificador',
        'tipo_archivo',
        'estado',
        'validado_por',
        'fecha_validacion',
    )
