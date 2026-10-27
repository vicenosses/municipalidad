from django import forms
from django.db.models import Q

from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from usuarios.sesion import get_delegacion_activa
from sgr.models import Indicador
from sgr.aportes import indicadores_para_actividad
from sgr.plazos import dentro_plazo


class AtencionCiudadanaForm(forms.ModelForm):
    indicador = forms.ModelChoiceField(label='Indicador SGR (opcional)', queryset=Indicador.objects.none(),
                                       required=False, widget=forms.Select(attrs={'class': 'form-select'}),
                                       help_text='Puede registrar la Actividad sin Indicador. Las opciones dependen de la fecha y Delegación.')
    valor_declarado = forms.DecimalField(label='Aporte declarado (si corresponde)', max_digits=12,
                                         decimal_places=2, min_value=0, required=False,
                                         widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}))
    class Meta:
        model = AtencionCiudadana
        fields = [
            'titulo',
            'fecha',
            'solicitante',
            'tipo',
            'subatencion',
            'va_al_tubo',
            'descripcion',
        ]
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'solicitante': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo'}),
            'subatencion': forms.Select(attrs={'class': 'form-select', 'id': 'id_subatencion'}),
            'va_al_tubo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

        labels = {'va_al_tubo': '¿Va al tubo?'}

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.delegacion_activa = get_delegacion_activa(request) if request else None
        fecha_texto = self.data.get(self.add_prefix('fecha')) if self.is_bound else self.initial.get('fecha')
        try:
            fecha = forms.DateField().clean(fecha_texto)
        except forms.ValidationError:
            fecha = None
        self.fields['indicador'].queryset = indicadores_para_actividad(fecha, self.delegacion_activa)
        self.fields['indicador'].error_messages['invalid_choice'] = 'No hay un Indicador válido para la fecha y Delegación seleccionadas.'
        tipos = TipoAtencion.objects.filter(activo=True)
        subatenciones = SubAtencion.objects.filter(
            activo=True,
            tipo__activo=True,
        )
        if self.delegacion_activa:
            scope = (
                Q(es_general=True, delegacion__isnull=True)
                | Q(es_general=False, delegacion=self.delegacion_activa)
            )
        else:
            scope = Q(es_general=True, delegacion__isnull=True)
        self.fields['tipo'].queryset = tipos.filter(scope)
        subatenciones = subatenciones.filter(scope).select_related('tipo', 'delegacion')
        if self.is_bound:
            tipo_id = self.data.get(self.add_prefix('tipo'))
            try:
                tipo = self.fields['tipo'].queryset.filter(pk=tipo_id).first()
            except (TypeError, ValueError):
                tipo = None
            if tipo is not None:
                subatenciones = subatenciones.filter(tipo=tipo)
                if not tipo.es_general:
                    subatenciones = subatenciones.filter(
                        es_general=False,
                        delegacion_id=tipo.delegacion_id,
                    )
        self.fields['subatencion'].queryset = subatenciones

    def clean(self):
        cleaned = super().clean()
        indicador = cleaned.get('indicador')
        if indicador:
            fecha = cleaned.get('fecha')
            if fecha and not dentro_plazo(fecha):
                self.add_error('indicador', 'La asociación solo se permite durante los primeros 3 días hábiles.')
            if indicador.unidad_medida == Indicador.Unidad.OTRA and cleaned.get('valor_declarado') is None:
                self.add_error('valor_declarado', 'Declare el aporte para esta unidad personalizada.')
        tipo = cleaned.get('tipo')
        sub = cleaned.get('subatencion')
        if tipo:
            if not tipo.activo:
                self.add_error('tipo', 'No se pueden usar categorías inactivas.')
            if not tipo.es_general and (
                self.delegacion_activa is None
                or tipo.delegacion_id != self.delegacion_activa.pk
            ):
                self.add_error('tipo', 'La categoría no pertenece a la delegación activa.')
        if sub:
            if not sub.activo:
                self.add_error('subatencion', 'No se pueden usar subcategorías inactivas.')
            if tipo and sub.tipo_id != tipo.pk:
                self.add_error(
                    'subatencion',
                    'La subcategoría no corresponde a la categoría seleccionada.',
                )
            elif tipo and not tipo.es_general and (
                sub.es_general
                or sub.delegacion_id != tipo.delegacion_id
            ):
                self.add_error(
                    'subatencion',
                    'La subcategoría debe pertenecer a la delegación de la categoría.',
                )
            elif tipo and tipo.es_general and not sub.es_general and (
                self.delegacion_activa is None
                or sub.delegacion_id != self.delegacion_activa.pk
            ):
                self.add_error(
                    'subatencion',
                    'La subcategoría no pertenece a la delegación activa.',
                )
        return cleaned


class AtencionVaAlTuboForm(forms.Form):
    va_al_tubo = forms.ChoiceField(
        label='¿Va al tubo?',
        choices=(('true', 'Sí'), ('false', 'No')),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )


class FiltroVaAlTuboForm(forms.Form):
    va_al_tubo = forms.ChoiceField(
        label='Va al tubo',
        required=False,
        choices=(
            ('', 'Todas'),
            ('true', 'Va al tubo'),
            ('false', 'No va al tubo'),
        ),
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'}),
    )
