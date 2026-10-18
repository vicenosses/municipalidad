from django import forms
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from evidencias.models import Evidencia
from usuarios.mixins import obtener_rol
from usuarios.sesion import delegaciones_autorizadas


def validar_archivo_imagen(archivo):
    content_type = getattr(archivo, 'content_type', '')
    if content_type not in {'image/jpeg', 'image/png'}:
        raise ValidationError('Solo se permiten archivos JPG o PNG.')
    try:
        archivo.seek(0)
        with Image.open(archivo) as imagen:
            if imagen.format not in {'JPEG', 'PNG'}:
                raise ValidationError('Solo se permiten archivos JPG o PNG.')
            imagen.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError('El archivo no contiene una imagen JPG o PNG válida.') from error
    finally:
        archivo.seek(0)


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
        if user is None or user.is_superuser or obtener_rol(user) == 'administrador':
            return
        if obtener_rol(user) == 'coordinador':
            self.fields['actividad'].queryset = self.fields['actividad'].queryset.filter(
                delegacion__in=delegaciones_autorizadas(user)
            )
        else:
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
