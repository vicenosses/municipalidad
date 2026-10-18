from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from agenda.models import Compromiso

User = get_user_model()


class CompromisoForm(forms.ModelForm):
    class Meta:
        model = Compromiso
        fields = ['titulo', 'descripcion', 'fecha_hora', 'responsable', 'estado']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'fecha_hora': forms.DateTimeInput(
                attrs={'class': 'form-control', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'responsable': forms.Select(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, delegacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha_hora'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        if delegacion is None:
            self.fields['responsable'].queryset = User.objects.none()
        else:
            self.fields['responsable'].queryset = User.objects.filter(
                Q(perfil__delegacion=delegacion)
                | Q(perfil__delegaciones=delegacion),
                is_active=True,
            ).distinct().order_by('username')
