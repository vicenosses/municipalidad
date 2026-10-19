from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from actividades.models import Actividad
from agenda.models import Compromiso
from usuarios.mixins import obtener_rol

User = get_user_model()


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
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields['fecha_hora'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['actividades'].queryset = Actividad.objects.none()
        manager = user is None or user.is_superuser or obtener_rol(user) in (
            'administrador',
            'coordinador',
        )
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
            self.fields['actividades'].queryset = Actividad.objects.filter(
                delegacion__in=delegaciones
            ).order_by('-fecha', 'titulo')
        if es_creacion:
            self.fields.pop('estado')
        elif not manager:
            for field in ('titulo', 'descripcion', 'solicitante', 'area_apoyo', 'fecha_hora', 'responsable'):
                self.fields.pop(field)
            self.fields.pop('motivo_cambio')

    def clean(self):
        cleaned_data = super().clean()
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
