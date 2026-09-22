from django import forms
from django.core.exceptions import ValidationError

from evidencias.models import Evidencia

TIPOS_PERMITIDOS = {'image/jpeg', 'image/png'}
EXTENSIONES_PERMITIDAS = {'.jpg', '.jpeg', '.png'}


def validar_archivo_imagen(archivo):
    content_type = getattr(archivo, 'content_type', '')
    nombre = (archivo.name or '').lower()
    if content_type not in TIPOS_PERMITIDOS and not any(nombre.endswith(ext) for ext in EXTENSIONES_PERMITIDAS):
        raise ValidationError('Solo se permiten archivos JPG o PNG.')
    if content_type and content_type not in TIPOS_PERMITIDOS:
        raise ValidationError('Solo se permiten archivos JPG o PNG.')


class EvidenciaForm(forms.ModelForm):
    class Meta:
        model = Evidencia
        fields = ['actividad', 'archivo']
        widgets = {
            'actividad': forms.Select(attrs={'class': 'form-select'}),
            'archivo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/png'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and not user.is_superuser:
            rol = getattr(getattr(user, 'perfil', None), 'rol', None)
            if rol not in ('administrador', 'coordinador', 'verificador'):
                self.fields['actividad'].queryset = self.fields['actividad'].queryset.filter(
                    funcionario=user
                )

    def clean_archivo(self):
        archivo = self.cleaned_data.get('archivo')
        if archivo:
            validar_archivo_imagen(archivo)
        return archivo


class ValidacionEvidenciaForm(forms.Form):
    comentario = forms.CharField(
        label='Comentario',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
