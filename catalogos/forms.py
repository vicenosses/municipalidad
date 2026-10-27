import secrets

from django import forms

from catalogos.models import (
    ItemMeta,
    SolicitudCatalogoGeneral,
    SubAtencion,
    TipoAtencion,
)
from catalogos.permisos import (
    catalogos_visibles,
    delegacion_catalogo,
    es_administrador_catalogos,
)


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
        fields = [
            'codigo',
            'nombre',
            'descripcion',
            'activo',
            'es_general',
            'delegacion',
        ]
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_general': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.delegacion_activa = delegacion_catalogo(request)
        self.es_administrador = es_administrador_catalogos(request) and self.delegacion_activa is None
        if self.es_administrador:
            return
        self.fields.pop('es_general')
        self.fields.pop('delegacion')

    def clean(self):
        cleaned_data = super().clean()
        if not self.es_administrador:
            if 'es_general' in self.data or 'delegacion' in self.data:
                raise forms.ValidationError(
                    'El alcance de este catálogo está fijado a su delegación.'
                )
            if self.delegacion_activa is None:
                raise forms.ValidationError('Debe tener una delegación activa autorizada.')
            self.instance.es_general = False
            self.instance.delegacion = self.delegacion_activa
        return cleaned_data


class SubAtencionForm(forms.ModelForm):
    class Meta:
        model = SubAtencion
        fields = [
            'nombre',
            'tipo',
            'activo',
            'es_general',
            'delegacion',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_general': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nombre'].help_text = 'El código se generará automáticamente al guardar.'
        self.fields['tipo'].label = 'Categoría'
        self.request = request
        self.delegacion_activa = delegacion_catalogo(request)
        self.es_administrador = es_administrador_catalogos(request) and self.delegacion_activa is None
        qs = TipoAtencion.objects.filter(activo=True)
        self.fields['tipo'].queryset = catalogos_visibles(qs, request)
        if self.instance.pk and self.instance.tipo_id:
            self.fields['tipo'].queryset |= TipoAtencion.objects.filter(
                pk=self.instance.tipo_id
            )
        if self.es_administrador:
            return
        self.fields.pop('es_general')
        self.fields.pop('delegacion')

    def clean(self):
        cleaned_data = super().clean()
        if not self.es_administrador:
            if 'es_general' in self.data or 'delegacion' in self.data:
                raise forms.ValidationError(
                    'El alcance de esta subcategoría está fijado a su delegación.'
                )
            if self.delegacion_activa is None:
                raise forms.ValidationError('Debe tener una delegación activa autorizada.')
            self.instance.es_general = False
            self.instance.delegacion = self.delegacion_activa

        tipo = cleaned_data.get('tipo')
        if tipo and not catalogos_visibles(
            TipoAtencion.objects.all(),
            self.request,
        ).filter(pk=tipo.pk).exists():
            self.add_error('tipo', 'La categoría no está dentro de su ámbito autorizado.')
        return cleaned_data


class SolicitudCatalogoGeneralForm(forms.ModelForm):
    class Meta:
        model = SolicitudCatalogoGeneral
        fields = ['codigo', 'nombre', 'descripcion', 'categoria_padre']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'categoria_padre': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, tipo_solicitud, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.tipo_solicitud = tipo_solicitud
        self.request = request
        if tipo_solicitud == SolicitudCatalogoGeneral.Tipo.CATEGORIA:
            self.fields.pop('categoria_padre')
        else:
            self.fields.pop('codigo')
            self.fields['nombre'].help_text = (
                'El código de la subcategoría se asignará automáticamente si se aprueba.'
            )
            self.fields['categoria_padre'].queryset = TipoAtencion.objects.filter(
                activo=True,
                es_general=True,
                delegacion__isnull=True,
            ).order_by('codigo')

    def clean(self):
        cleaned_data = super().clean()
        padre = cleaned_data.get('categoria_padre')
        if self.tipo_solicitud == SolicitudCatalogoGeneral.Tipo.SUBCATEGORIA:
            if padre is None:
                self.add_error('categoria_padre', 'Seleccione una categoría general activa.')
            elif not padre.activo or not padre.es_general or padre.delegacion_id is not None:
                self.add_error(
                    'categoria_padre',
                    'La subcategoría general requiere una categoría general activa.',
                )
        return cleaned_data

    def save(self, commit=True):
        solicitud = super().save(commit=False)
        solicitud.tipo_solicitud = self.tipo_solicitud
        if self.tipo_solicitud == SolicitudCatalogoGeneral.Tipo.SUBCATEGORIA:
            solicitud.codigo = f'SOL-SUB-{secrets.token_hex(10)}'
        solicitud.solicitante = self.request.user
        solicitud.delegacion_solicitante = delegacion_catalogo(self.request)
        solicitud.estado = SolicitudCatalogoGeneral.Estado.PENDIENTE
        solicitud.decidido_por = None
        solicitud.fecha_decision = None
        if commit:
            solicitud.save()
        return solicitud
