from decimal import Decimal

from django import forms

from sgr.aportes import indicadores_para_actividad
from sgr.models import AporteIndicador, Indicador


class PropuestaAporteForm(forms.Form):
    indicador = forms.ModelChoiceField(queryset=Indicador.objects.none(),
                                       widget=forms.Select(attrs={'class': 'form-select'}))
    valor_declarado = forms.DecimalField(label='Aporte declarado', max_digits=12, decimal_places=2,
                                         min_value=Decimal('0'), required=False,
                                         widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    version = forms.IntegerField(label='', min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, actividad, aporte=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['indicador'].queryset = indicadores_para_actividad(actividad.fecha, actividad.delegacion)
        self.initial['version'] = aporte.version if aporte else 0
        if aporte:
            self.initial.update(indicador=aporte.indicador_id, valor_declarado=aporte.valor_declarado)
            if aporte.estado == AporteIndicador.Estado.REQUIERE_CORRECCION:
                self.fields['indicador'].disabled = not aporte.corregir_indicador
                self.fields['valor_declarado'].disabled = not aporte.corregir_valor


class ValidacionAporteForm(forms.Form):
    estado = forms.ChoiceField(label='Decisión', choices=(
        (AporteIndicador.Estado.CUMPLE, 'Cumple'),
        (AporteIndicador.Estado.REQUIERE_CORRECCION, 'Requiere corrección'),
        (AporteIndicador.Estado.NO_CUMPLE, 'No cumple'),
    ), widget=forms.Select(attrs={'class': 'form-select'}))
    valor_validado = forms.DecimalField(label='Valor validado (vacío: aprobar el declarado)',
                                        max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False,
                                        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    comentario = forms.CharField(required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    corregir_indicador = forms.BooleanField(label='Autorizar corrección del Indicador', required=False)
    corregir_valor = forms.BooleanField(label='Autorizar corrección del aporte declarado', required=False)
    version = forms.IntegerField(label='', min_value=1, widget=forms.HiddenInput)
