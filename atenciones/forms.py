from django import forms

from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion


class AtencionCiudadanaForm(forms.ModelForm):
    class Meta:
        model = AtencionCiudadana
        fields = ['solicitante', 'tipo', 'subatencion', 'descripcion']
        widgets = {
            'solicitante': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo'}),
            'subatencion': forms.Select(attrs={'class': 'form-select', 'id': 'id_subatencion'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo'].queryset = TipoAtencion.objects.filter(activo=True)
        self.fields['subatencion'].queryset = SubAtencion.objects.filter(activo=True).select_related('tipo')

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        sub = cleaned.get('subatencion')
        if tipo and sub and sub.tipo_id != tipo.id:
            self.add_error('subatencion', 'La subatención no corresponde al tipo seleccionado.')
        return cleaned
