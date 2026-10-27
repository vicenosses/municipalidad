from django import forms

from sgr.models import Periodo


class PeriodoInformeField(forms.ModelChoiceField):
    def label_from_instance(self, periodo):
        estado = 'activo' if periodo.activo else 'inactivo'
        return (f'{periodo.nombre} ({periodo.fecha_inicio:%d/%m/%Y} - '
                f'{periodo.fecha_fin:%d/%m/%Y}; {estado})')


class InformeFiltroForm(forms.Form):
    periodo = PeriodoInformeField(
        label='Período', queryset=Periodo.objects.all(), required=False,
        empty_label='Período activo vigente',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
