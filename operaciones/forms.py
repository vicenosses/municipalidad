from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from cartas.models import Carta, DocumentoCarta
from gestion_social.models import GestionSocial, SeguimientoGestionSocial
from hitos.models import Hito
from sgr.models import AsignacionMeta
from usuarios.mixins import obtener_rol
from usuarios.models import Delegacion, Territorio, Vecino
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa

User = get_user_model()
ROLES_GESTORES = ('administrador', 'delegado', 'coordinador')


def _usuarios_de_delegaciones(delegaciones):
    return User.objects.filter(
        Q(perfil__delegacion__in=delegaciones)
        | Q(perfil__delegaciones__in=delegaciones),
        is_active=True,
        perfil__activo=True,
    ).distinct().order_by('first_name', 'last_name', 'username')


class FormularioTerritorial(forms.ModelForm):
    motivo_cambio = forms.CharField(
        label='Motivo de reasignación',
        required=False,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.gestor = obtener_rol(request.user) in ROLES_GESTORES
        self.delegaciones = delegaciones_autorizadas(request.user)
        delegacion = get_delegacion_activa(request)
        if obtener_rol(request.user) != 'administrador' and delegacion:
            self.delegaciones = self.delegaciones.filter(pk=delegacion.pk)

        if 'delegacion' in self.fields:
            self.fields['delegacion'].queryset = self.delegaciones
            if not self.gestor:
                self.fields.pop('delegacion')
                if delegacion:
                    self.instance.delegacion = delegacion
            elif delegacion:
                self.fields['delegacion'].initial = delegacion.pk

        if 'responsable' in self.fields:
            self.fields['responsable'].queryset = _usuarios_de_delegaciones(self.delegaciones)
            if not self.gestor:
                self.fields.pop('responsable')
                self.instance.responsable = request.user
        if not self.gestor:
            self.fields.pop('motivo_cambio', None)

        for field in self.fields.values():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs.setdefault('class', 'form-select')
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif not isinstance(field.widget, forms.HiddenInput):
                field.widget.attrs.setdefault('class', 'form-control')

    def clean_delegacion(self):
        delegacion = self.cleaned_data.get('delegacion')
        return delegacion or get_delegacion_activa(self.request)

    def clean(self):
        cleaned_data = super().clean()
        responsable = cleaned_data.get('responsable')
        if (
            self.instance.pk
            and responsable
            and responsable.pk != self.instance.responsable_id
            and not cleaned_data.get('motivo_cambio', '').strip()
        ):
            self.add_error('motivo_cambio', 'Indique el motivo de la reasignación.')
        return cleaned_data


class CartaForm(FormularioTerritorial):
    class Meta:
        model = Carta
        fields = (
            'remitente', 'destinatario', 'telefono', 'asunto', 'contenido',
            'vecino', 'delegacion', 'territorio', 'responsable', 'area_derivada',
            'fecha_ingreso', 'fecha_compromiso', 'fecha_actividad',
            'observaciones', 'ingresa_al_tubo',
        )
        widgets = {
            'contenido': forms.Textarea(attrs={'rows': 5}),
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date'}),
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['territorio'].queryset = Territorio.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        self.fields['vecino'].queryset = Vecino.objects.filter(
            territorio__delegacion__in=self.delegaciones, activo=True,
        ).select_related('territorio')
        delegacion_id = self.data.get('delegacion') or self.instance.delegacion_id
        if delegacion_id:
            self.fields['territorio'].queryset = self.fields['territorio'].queryset.filter(
                delegacion_id=delegacion_id,
            )
            self.fields['vecino'].queryset = self.fields['vecino'].queryset.filter(
                territorio__delegacion_id=delegacion_id,
            )

    def clean(self):
        cleaned_data = super().clean()
        delegacion = cleaned_data.get('delegacion') or getattr(self.instance, 'delegacion', None)
        if delegacion and 'territorio' in cleaned_data:
            self.fields['territorio'].queryset = Territorio.objects.filter(
                delegacion=delegacion, activo=True,
            )
        if delegacion and 'vecino' in cleaned_data:
            self.fields['vecino'].queryset = Vecino.objects.filter(
                territorio__delegacion=delegacion, activo=True,
            )
        return cleaned_data


class CartaDocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoCarta
        fields = ('archivo', 'descripcion')
        widgets = {
            'archivo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
        }


class GestionSocialForm(FormularioTerritorial):
    class Meta:
        model = GestionSocial
        fields = (
            'titulo', 'tipo', 'subtipo', 'descripcion', 'resultado',
            'vecino', 'asignacion_meta', 'delegacion', 'territorio',
            'responsable', 'fecha_ingreso', 'fecha_compromiso',
            'ingresa_al_tubo',
        )
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 5}),
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date'}),
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['vecino'].required = True
        self.fields['territorio'].queryset = Territorio.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        self.fields['vecino'].queryset = Vecino.objects.filter(
            territorio__delegacion__in=self.delegaciones, activo=True,
        ).select_related('territorio')
        self.fields['asignacion_meta'].queryset = AsignacionMeta.objects.filter(
            activa=True, meta__activo=True, meta__periodo__activo=True,
            meta__delegacion__in=self.delegaciones,
        ).select_related('meta', 'funcionario', 'meta__periodo')
        delegacion_id = self.data.get('delegacion') or self.instance.delegacion_id
        if delegacion_id:
            self.fields['territorio'].queryset = self.fields['territorio'].queryset.filter(
                delegacion_id=delegacion_id,
            )
            self.fields['vecino'].queryset = self.fields['vecino'].queryset.filter(
                territorio__delegacion_id=delegacion_id,
            )
            self.fields['asignacion_meta'].queryset = self.fields['asignacion_meta'].queryset.filter(
                meta__delegacion_id=delegacion_id,
            )
        responsable_id = self.data.get('responsable') or self.instance.responsable_id
        if not self.gestor:
            responsable_id = self.request.user.pk
        if responsable_id:
            self.fields['asignacion_meta'].queryset = self.fields['asignacion_meta'].queryset.filter(
                funcionario_id=responsable_id,
            )

    def clean(self):
        cleaned_data = super().clean()
        delegacion = cleaned_data.get('delegacion') or getattr(self.instance, 'delegacion', None)
        if delegacion and 'territorio' in cleaned_data:
            self.fields['territorio'].queryset = Territorio.objects.filter(
                delegacion=delegacion, activo=True,
            )
        if delegacion and 'vecino' in cleaned_data:
            self.fields['vecino'].queryset = Vecino.objects.filter(
                territorio__delegacion=delegacion, activo=True,
            )
        return cleaned_data


class HitoForm(FormularioTerritorial):
    class Meta:
        model = Hito
        fields = (
            'titulo', 'descripcion', 'actividad', 'actividades',
            'gestion_social', 'compromiso', 'territorio', 'responsable',
            'asignacion_meta', 'fecha_programada', 'periodicidad',
            'repetir_hasta',
        )
        widgets = {
            'fecha_programada': forms.DateInput(attrs={'type': 'date'}),
            'repetir_hasta': forms.DateInput(attrs={'type': 'date'}),
        }
        help_texts = {
            'actividad': 'Seleccione solo si el hito corresponde a una actividad.',
            'actividades': 'Puede relacionar varias actividades a este hito.',
            'gestion_social': 'Seleccione solo si el hito corresponde a una gestión social.',
            'compromiso': 'Seleccione solo si el hito corresponde a un compromiso.',
            'asignacion_meta': 'Muestra el objetivo, ponderación y período asignados a la persona responsable.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['actividad'].queryset = AtencionCiudadana.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        self.fields['gestion_social'].queryset = GestionSocial.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        self.fields['compromiso'].queryset = Compromiso.objects.filter(
            delegacion__in=self.delegaciones,
        ).select_related('delegacion')
        self.fields['actividades'].queryset = AtencionCiudadana.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        self.fields['territorio'].queryset = Territorio.objects.filter(
            delegacion__in=self.delegaciones, activo=True,
        ).select_related('delegacion')
        responsable_id = self.data.get('responsable') or self.instance.responsable_id
        self.fields['asignacion_meta'].queryset = AsignacionMeta.objects.filter(
            activa=True, meta__activo=True, meta__periodo__activo=True,
            meta__delegacion__in=self.delegaciones,
        ).select_related('meta', 'funcionario', 'meta__periodo')
        if responsable_id:
            self.fields['asignacion_meta'].queryset = self.fields['asignacion_meta'].queryset.filter(
                funcionario_id=responsable_id,
            )

    def clean(self):
        cleaned_data = super().clean()
        selected = cleaned_data.get('actividades')
        principal = cleaned_data.get('actividad')
        if principal and selected is not None and principal not in selected:
            cleaned_data['actividades'] = selected | AtencionCiudadana.objects.filter(pk=principal.pk)
        selected = cleaned_data.get('actividades')
        if selected is not None:
            actuales = (
                set(self.instance.actividades.values_list('pk', flat=True))
                if self.instance.pk else set()
            )
            seleccionadas = set(selected.values_list('pk', flat=True))
            modificadas = actuales ^ seleccionadas
            from sgr.periodos import validar_periodo_abierto

            for actividad in AtencionCiudadana.objects.filter(pk__in=modificadas):
                try:
                    validar_periodo_abierto(
                        actividad.fecha,
                        'No se puede cambiar la relación con una actividad de un período cerrado.',
                    )
                except ValidationError as error:
                    self.add_error('actividades', error)
                    break
        return cleaned_data


class SeguimientoGestionSocialForm(forms.ModelForm):
    class Meta:
        model = SeguimientoGestionSocial
        fields = (
            'tipo', 'fecha', 'area_institucion', 'beneficio',
            'resultado', 'observaciones', 'evidencia',
        )
        widgets = {'fecha': forms.DateInput(attrs={'type': 'date'})}


class CambioEstadoForm(forms.Form):
    estado = forms.ChoiceField(label='Nuevo estado')
    respuesta = forms.CharField(
        label='Pronunciamiento o respuesta', required=False,
        widget=forms.Textarea(attrs={'rows': 4}),
    )
    fecha_completada = forms.DateField(
        label='Fecha de término', required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    motivo = forms.CharField(
        label='Motivo', required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['estado'].choices = choices
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-select' if isinstance(
                field.widget, forms.Select,
            ) else 'form-control')

    def clean(self):
            cleaned_data = super().clean()
            if (
                cleaned_data.get('estado') == Carta.Estado.RESPONDIDA
                or cleaned_data.get('estado') == Carta.Estado.APROBADA
            ) and not cleaned_data.get('respuesta', '').strip():
                self.add_error('respuesta', 'Ingrese el pronunciamiento antes de marcar la carta como respondida.')
            return cleaned_data
