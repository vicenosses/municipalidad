from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from atenciones.models import AtencionCiudadana
from agenda.models import Compromiso, SolicitudAmpliacion
from usuarios.mixins import obtener_rol

User = get_user_model()
ROLES_GESTORES = ('administrador', 'delegado', 'coordinador')


class SolicitudAmpliacionForm(forms.ModelForm):
    class Meta:
        model = SolicitudAmpliacion
        fields = ['plazo_propuesto', 'motivo']
        labels = {'plazo_propuesto': 'Nueva fecha y hora límite', 'motivo': 'Motivo de la solicitud'}
        widgets = {'plazo_propuesto': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}, format='%Y-%m-%dT%H:%M'),
                   'motivo': forms.Textarea(attrs={'class': 'form-control', 'rows': 3})}

    def __init__(self, *args, compromiso, **kwargs):
        super().__init__(*args, **kwargs)
        self.compromiso = compromiso
        self.fields['plazo_propuesto'].input_formats = ['%Y-%m-%dT%H:%M']

    def clean_plazo_propuesto(self):
        plazo = self.cleaned_data['plazo_propuesto']
        if timezone.localtime(plazo).date() <= timezone.localtime(self.compromiso.fecha_hora).date():
            raise forms.ValidationError('La nueva fecha debe ser posterior al plazo actual.')
        return plazo


class CompromisoForm(forms.ModelForm):
    motivo_cambio = forms.CharField(
        label='Motivo de reasignación',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    class Meta:
        model = Compromiso
        fields = [
            'titulo',
            'descripcion',
            'solicitante',
            'area_apoyo',
            'fecha_hora',
            'responsable',
            'estado',
            'observaciones',
            'actividades',
        ]
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'solicitante': forms.TextInput(attrs={'class': 'form-control'}),
            'area_apoyo': forms.TextInput(attrs={'class': 'form-control'}),
            'fecha_hora': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'responsable': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'actividades': forms.SelectMultiple(attrs={'class': 'form-select'}),
        }

    transiciones = {
        Compromiso.Estado.INGRESADO: {Compromiso.Estado.PENDIENTE},
        Compromiso.Estado.PENDIENTE: {Compromiso.Estado.EN_PROCESO},
        Compromiso.Estado.EN_PROCESO: {Compromiso.Estado.REALIZADO},
        Compromiso.Estado.REALIZADO: set(),
    }

    def __init__(
        self,
        *args,
        delegacion=None,
        delegaciones=None,
        user=None,
        es_creacion=False,
        actividad_origen=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.user = user
        self.actividad_origen = actividad_origen
        self.fields['fecha_hora'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['actividades'].queryset = AtencionCiudadana.objects.none()
        manager = user is None or user.is_superuser or obtener_rol(user) in ROLES_GESTORES
        if delegaciones is None and delegacion is not None:
            delegaciones = [delegacion]
        if delegaciones is None:
            self.fields['responsable'].queryset = User.objects.none()
        else:
            if manager or es_creacion:
                self.fields['responsable'].queryset = User.objects.filter(
                    Q(perfil__delegacion__in=delegaciones)
                    | Q(perfil__delegaciones__in=delegaciones),
                    is_active=True,
                ).distinct().order_by('username')
            elif self.instance.responsable_id:
                self.fields['responsable'].queryset = User.objects.filter(
                    pk=self.instance.responsable_id
                )
            else:
                self.fields['responsable'].queryset = User.objects.none()
            self.fields['actividades'].queryset = AtencionCiudadana.objects.filter(
                delegacion__in=delegaciones,
                activo=True,
            ).order_by('-fecha', 'titulo')
            if actividad_origen is not None:
                self.fields['actividades'].queryset = (
                    self.fields['actividades'].queryset.exclude(
                        estado=AtencionCiudadana.Estado.CERRADA
                    )
                )
                self.fields['actividades'].label = 'Actividades relacionadas'
                self.fields['actividades'].help_text = (
                    'La actividad de origen se asociará automáticamente. '
                    'Puede agregar otras actividades de la misma delegación.'
                )
            if self.instance.pk:
                self.fields['actividades'].queryset = (
                    self.fields['actividades'].queryset
                    | self.instance.actividades.filter(activo=False, delegacion_id=self.instance.delegacion_id)
                )
        if es_creacion:
            self.fields.pop('estado')
        elif not manager:
            for field in tuple(self.fields):
                if field != 'estado':
                    self.fields.pop(field)
        if self.instance.pk and 'fecha_hora' in self.fields:
            self.fields['fecha_hora'].disabled = True
            self.fields['fecha_hora'].help_text = 'Para ampliar el plazo, presente una solicitud desde el detalle del compromiso.'

    def clean(self):
        cleaned_data = super().clean()
        if self.actividad_origen is not None and 'actividades' in cleaned_data:
            actividades = cleaned_data['actividades']
            origen = AtencionCiudadana.objects.filter(
                pk=self.actividad_origen.pk,
                delegacion_id=self.actividad_origen.delegacion_id,
                activo=True,
            ).exclude(
                estado=AtencionCiudadana.Estado.CERRADA
            )
            cleaned_data['actividades'] = (actividades | origen).distinct()
        if self.instance.pk and 'actividades' in cleaned_data:
            actividades = cleaned_data['actividades']
            historicas = self.instance.actividades.filter(activo=False, delegacion_id=self.instance.delegacion_id)
            cleaned_data['actividades'] = (
                actividades | historicas
            ).distinct()
        if self.instance.pk and 'estado' in cleaned_data:
            anterior = self.instance.estado
            nuevo = cleaned_data['estado']
            if nuevo != anterior and nuevo not in self.transiciones.get(anterior, set()):
                self.add_error('estado', 'La transición de estado seleccionada no está permitida.')
        if self.instance.pk and 'responsable' in cleaned_data:
            anterior = self.instance.responsable_id
            nuevo = cleaned_data['responsable'].pk
            motivo = cleaned_data.get('motivo_cambio', '').strip()
            if nuevo != anterior and not motivo:
                self.add_error('motivo_cambio', 'Indique el motivo para reasignar el compromiso.')
            cleaned_data['motivo_cambio'] = motivo
        return cleaned_data

    def clean_titulo(self):
        return self.cleaned_data['titulo'].strip()


class CompromisoFiltroForm(forms.Form):
    q = forms.CharField(
        label='Buscar',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Título o solicitante'}),
    )
    estado = forms.ChoiceField(
        label='Estado',
        required=False,
        choices=[('', 'Todos')] + list(Compromiso.Estado.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    responsable = forms.ModelChoiceField(
        label='Responsable',
        required=False,
        queryset=User.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    desde = forms.DateField(
        label='Desde',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    hasta = forms.DateField(
        label='Hasta',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def __init__(self, *args, responsables=None, **kwargs):
        super().__init__(*args, **kwargs)
        if responsables is not None:
            self.fields['responsable'].queryset = responsables

    def clean(self):
        cleaned_data = super().clean()
        desde = cleaned_data.get('desde')
        hasta = cleaned_data.get('hasta')
        if desde and hasta and desde > hasta:
            self.add_error('hasta', 'La fecha final debe ser igual o posterior a la inicial.')
        return cleaned_data
