from django import forms

from sgr.models import Indicador, Meta, Periodo
from sgr.permisos import metas_visibles
from usuarios.mixins import obtener_rol
from usuarios.models import Delegacion
from usuarios.sesion import get_delegacion_activa


class PeriodoForm(forms.ModelForm):
    class Meta:
        model = Periodo
        fields = ('nombre', 'fecha_inicio', 'fecha_fin')
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_inicio': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control', 'type': 'date',
            }),
            'fecha_fin': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control', 'type': 'date',
            }),
        }


class PeriodoFiltroForm(forms.Form):
    estado = forms.ChoiceField(
        label='Estado', required=False,
        choices=(('', 'Todos'), ('activo', 'Activos'), ('inactivo', 'Inactivos')),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    anio = forms.IntegerField(label='Año', required=False, min_value=1, max_value=9999,
                              widget=forms.NumberInput(attrs={'class': 'form-control'}))
    buscar = forms.CharField(label='Buscar por nombre', required=False, max_length=150,
                             widget=forms.TextInput(attrs={'class': 'form-control'}))


class MetaForm(forms.ModelForm):
    class Meta:
        model = Meta
        fields = ('periodo', 'delegacion', 'nombre', 'descripcion')
        widgets = {
            'periodo': forms.Select(attrs={'class': 'form-select'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, request, periodo_origen=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields.pop('periodo')
            self.fields.pop('delegacion')
        else:
            self.fields['periodo'].queryset = Periodo.objects.filter(activo=True)
            delegacion = get_delegacion_activa(request)
            if obtener_rol(request.user) == 'administrador' and delegacion is not None:
                self.fields['delegacion'].queryset = Delegacion.objects.filter(pk=delegacion.pk)
                self.fields['delegacion'].initial = delegacion.pk
            if periodo_origen is not None:
                self.instance.periodo = periodo_origen
                self.fields['periodo'].initial = periodo_origen.pk
                self.fields['periodo'].disabled = True
            if obtener_rol(request.user) != 'administrador':
                self.fields.pop('delegacion')
                self.instance.delegacion = get_delegacion_activa(request)


class MetaFiltroForm(forms.Form):
    periodo = forms.ModelChoiceField(
        label='Período', queryset=Periodo.objects.all(), required=False, empty_label='Todos',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    estado = forms.ChoiceField(
        label='Estado', required=False,
        choices=(('', 'Todas'), ('activa', 'Activas'), ('inactiva', 'Inactivas')),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegacion = forms.ModelChoiceField(
        label='Delegación', queryset=Delegacion.objects.all(), required=False, empty_label='Todas',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    buscar = forms.CharField(label='Buscar', required=False, max_length=200,
                             widget=forms.TextInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        if obtener_rol(request.user) != 'administrador':
            self.fields.pop('delegacion')
        elif get_delegacion_activa(request) is not None:
            self.fields['delegacion'].queryset = Delegacion.objects.filter(pk=get_delegacion_activa(request).pk)


class IndicadorForm(forms.ModelForm):
    motivo_ponderacion = forms.CharField(label='Motivo del cambio de ponderación', required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    motivo_objetivo = forms.CharField(label='Motivo del cambio de objetivo', required=False,
                                      widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    class Meta:
        model = Indicador
        fields = ('meta', 'nombre', 'descripcion', 'unidad_medida', 'unidad_personalizada',
                  'sentido', 'valor_objetivo', 'ponderacion')
        widgets = {
            'meta': forms.Select(attrs={'class': 'form-select'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'unidad_medida': forms.Select(attrs={'class': 'form-select'}),
            'unidad_personalizada': forms.TextInput(attrs={'class': 'form-control'}),
            'sentido': forms.Select(attrs={'class': 'form-select'}),
            'valor_objetivo': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'step': '0.01'}),
            'ponderacion': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'max': '100', 'step': '0.01'}),
        }
        help_texts = {'unidad_personalizada': 'Obligatoria al elegir Otra. Se ignora para unidades estándar.'}

    def __init__(self, *args, request, meta_origen=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields['valor_objetivo'].widget.attrs['min'] = '0.01' if self.instance.activo else '0'
        self.fields['valor_objetivo'].help_text = 'El objetivo debe ser mayor que cero para mantener el Indicador activo.'
        if not self.instance.pk or not self.instance.tiene_vinculaciones:
            self.fields.pop('motivo_objetivo')
            self.fields.pop('motivo_ponderacion')
        self.fields['ponderacion'].widget.attrs['min'] = '0.01' if self.instance.activo else '0'
        if self.instance.pk:
            self.fields.pop('meta')
        else:
            self.fields['meta'].queryset = metas_visibles(request).filter(activo=True, periodo__activo=True)
            if meta_origen is not None:
                self.instance.meta = meta_origen
                self.fields['meta'].initial = meta_origen.pk
                self.fields['meta'].disabled = True

    def clean(self):
        datos = super().clean()
        self.instance._motivo_objetivo = datos.get('motivo_objetivo', '')
        self.instance._actor_objetivo = self.request.user
        self.instance._request_objetivo = self.request
        self.instance._motivo_ponderacion = datos.get('motivo_ponderacion', '')
        self.instance._actor_ponderacion = self.request.user
        self.instance._request_ponderacion = self.request
        return datos


class IndicadorFiltroForm(MetaFiltroForm):
    meta = forms.ModelChoiceField(label='Meta', queryset=Meta.objects.none(), required=False,
                                  empty_label='Todas', widget=forms.Select(attrs={'class': 'form-select'}))
    unidad = forms.ChoiceField(label='Unidad', required=False,
                               choices=(('', 'Todas'), *Indicador.Unidad.choices),
                               widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, request=request, **kwargs)
        self.fields['meta'].queryset = metas_visibles(request)
        self.fields['estado'].choices = (('', 'Todos'), ('activo', 'Activos'), ('inactivo', 'Inactivos'))
