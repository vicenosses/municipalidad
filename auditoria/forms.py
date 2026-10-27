from django import forms
from django.contrib.auth import get_user_model

from auditoria.presentacion import MODULOS, etiqueta_accion


class AuditoriaFiltroForm(forms.Form):
    accion = forms.ChoiceField(label='Acción', required=False,
                              widget=forms.Select(attrs={'class': 'form-select'}))
    modulo = forms.ChoiceField(label='Módulo', required=False,
                              widget=forms.Select(attrs={'class': 'form-select'}))
    buscar = forms.CharField(label='Buscar', required=False, max_length=240,
                             widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, registros=None, **kwargs):
        super().__init__(*args, **kwargs)
        usuarios = get_user_model().objects.none()
        acciones = []
        modelos = set()
        if registros is not None:
            usuarios = get_user_model().objects.filter(
                pk__in=registros.order_by().values('usuario_id')
            ).order_by('username')
            acciones = registros.order_by('accion').values_list('accion', flat=True).distinct()
            modelos = set(registros.order_by().values_list('modelo', flat=True).distinct())
        self.fields['usuario'].queryset = usuarios
        self.fields['accion'].choices = [('', 'Todas')] + [
            (accion, etiqueta_accion(accion)) for accion in acciones
        ]
        self.fields['modulo'].choices = [('', 'Todos')] + [
            (codigo, nombre) for codigo, (nombre, etiquetas) in MODULOS.items()
            if modelos.intersection(etiquetas)
        ]

    usuario = forms.ModelChoiceField(
        label='Usuario',
        queryset=get_user_model().objects.none(),
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
