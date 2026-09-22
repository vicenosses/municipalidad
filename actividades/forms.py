from django import forms

from actividades.models import Actividad


class ActividadForm(forms.ModelForm):
    class Meta:
        model = Actividad
        fields = ['titulo', 'descripcion', 'fecha', 'estado']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'fecha': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_titulo(self):
        titulo = self.cleaned_data['titulo'].strip()
        if not titulo:
            raise forms.ValidationError('El título es obligatorio.')
        return titulo

    def clean_descripcion(self):
        descripcion = self.cleaned_data['descripcion'].strip()
        if not descripcion:
            raise forms.ValidationError('La descripción es obligatoria.')
        return descripcion
