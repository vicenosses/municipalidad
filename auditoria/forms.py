from django import forms
from django.contrib.auth import get_user_model


class AuditoriaFiltroForm(forms.Form):
    usuario = forms.ModelChoiceField(
        label='Usuario',
        queryset=get_user_model().objects.order_by('username'),
        required=False,
        empty_label='Todos',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    fecha_desde = forms.DateField(
        label='Desde',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    fecha_hasta = forms.DateField(
        label='Hasta',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def clean(self):
        datos = super().clean()
        desde = datos.get('fecha_desde')
        hasta = datos.get('fecha_hasta')
        if desde and hasta and desde > hasta:
            self.add_error('fecha_hasta', 'La fecha hasta debe ser igual o posterior a la fecha desde.')
        return datos
