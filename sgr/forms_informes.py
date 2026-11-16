from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from sgr.models import Meta, Periodo
from usuarios.mixins import obtener_rol
from usuarios.models import Delegacion
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa


class PeriodoInformeField(forms.ModelChoiceField):
    def label_from_instance(self, periodo):
        estado = 'activo' if periodo.activo else 'inactivo'
        return (f'{periodo.nombre} ({periodo.fecha_inicio:%d/%m/%Y} - '
                f'{periodo.fecha_fin:%d/%m/%Y}; {estado})')


class InformeFiltroForm(forms.Form):
    periodo = PeriodoInformeField(
        label='Período', queryset=Periodo.objects.all(), required=False,
        empty_label='Período activo vigente',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegacion = forms.ModelChoiceField(
        label='Delegación', queryset=Delegacion.objects.none(), required=False,
        empty_label='Todas las delegaciones', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    funcionario = forms.ModelChoiceField(
        label='Funcionario', queryset=get_user_model().objects.none(), required=False,
        empty_label='Todos los funcionarios', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    meta = forms.ModelChoiceField(
        label='Meta', queryset=Meta.objects.none(), required=False,
        empty_label='Todas las metas', widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        if self.is_bound:
            self.data = self.data.copy()
        if request is None:
            self.fields['delegacion'].queryset = Delegacion.objects.filter(activa=True)
            self.fields['funcionario'].queryset = get_user_model().objects.filter(is_active=True)
            self.fields['meta'].queryset = Meta.objects.all()
            return

        rol = obtener_rol(request.user)
        delegaciones = delegaciones_autorizadas(request.user)
        activa = get_delegacion_activa(request)
        if rol == 'administrador':
            if activa:
                delegaciones = delegaciones.filter(pk=activa.pk)
            self.fields['delegacion'].queryset = delegaciones
            delegacion_id = self.data.get('delegacion') if self.is_bound else None
            if activa and delegacion_id and not delegaciones.filter(pk=delegacion_id).exists():
                self.data['delegacion'] = str(activa.pk)
        else:
            self.fields.pop('delegacion')
            delegaciones = delegaciones.filter(pk=activa.pk) if activa else delegaciones.none()

        if 'delegacion' in self.fields:
            delegacion_id = self.data.get('delegacion') if self.is_bound else None
            if delegacion_id:
                delegaciones = delegaciones.filter(pk=delegacion_id)
        self.fields['funcionario'].queryset = get_user_model().objects.filter(
            is_active=True,
            perfil__activo=True,
            perfil__delegaciones__in=delegaciones,
        ).distinct().order_by('last_name', 'first_name', 'username')

        periodo_id = self.data.get('periodo') if self.is_bound else None
        metas = Meta.objects.all()
        if periodo_id and str(periodo_id).isdecimal():
            metas = metas.filter(periodo_id=periodo_id)
        elif periodo_id:
            metas = metas.none()
        else:
            hoy = timezone.localdate()
            metas = metas.filter(
                periodo__activo=True,
                periodo__fecha_inicio__lte=hoy,
                periodo__fecha_fin__gte=hoy,
            )
        if delegaciones is not None:
            metas = metas.filter(delegacion__in=delegaciones)
        self.fields['meta'].queryset = metas.order_by('nombre', 'pk')
        if self.is_bound:
            meta_id = self.data.get('meta')
            funcionario_id = self.data.get('funcionario')
            if meta_id and str(meta_id).isdecimal() and not metas.filter(pk=meta_id).exists():
                self.data.pop('meta', None)
            funcionarios = self.fields['funcionario'].queryset
            if (
                funcionario_id
                and str(funcionario_id).isdecimal()
                and not funcionarios.filter(pk=funcionario_id).exists()
            ):
                self.data.pop('funcionario', None)
