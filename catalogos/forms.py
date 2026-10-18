from django import forms
from django.db.models import Q

from catalogos.models import ItemMeta, SubAtencion, TipoAtencion


class ItemMetaForm(forms.ModelForm):
    class Meta:
        model = ItemMeta
        fields = ['codigo', 'nombre', 'descripcion', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TipoAtencionForm(forms.ModelForm):
    class Meta:
        model = TipoAtencion
        fields = ['codigo', 'nombre', 'descripcion', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class SubAtencionForm(forms.ModelForm):
    class Meta:
        model = SubAtencion
        fields = ['codigo', 'nombre', 'tipo', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = TipoAtencion.objects.filter(activo=True)
        if self.instance.pk and self.instance.tipo_id:
            qs = TipoAtencion.objects.filter(Q(activo=True) | Q(pk=self.instance.tipo_id))
        self.fields['tipo'].queryset = qs
