from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.models import Delegacion, Territorio
from usuarios.sesion import filtrar_contexto_territorial, get_delegacion_activa


class TerritorioForm(forms.ModelForm):
    class Meta:
        model = Territorio
        fields = ('nombre', 'descripcion', 'delegacion', 'activo')
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        delegacion = get_delegacion_activa(request)
        self.fields['delegacion'].queryset = Delegacion.objects.filter(activa=True)
        if delegacion:
            self.fields['delegacion'].queryset = self.fields['delegacion'].queryset.filter(pk=delegacion.pk)
            self.fields['delegacion'].initial = delegacion.pk


class TerritoriosView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado', 'coordinador')

    def get(self, request):
        territorios = filtrar_contexto_territorial(Territorio.objects.select_related('delegacion'), request)
        busqueda = request.GET.get('q', '').strip()
        if busqueda:
            territorios = territorios.filter(nombre__icontains=busqueda)
        return render(request, 'usuarios/territorios/lista.html', {'territorios': territorios, 'q': busqueda,
                      'puede_editar': obtener_rol(request.user) == 'administrador'})


class TerritorioGuardarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def objeto(self, request, pk):
        if pk is None:
            return None
        qs = filtrar_contexto_territorial(Territorio.objects.all(), request)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk=None):
        form = TerritorioForm(request=request, instance=self.objeto(request, pk))
        return render(request, 'usuarios/territorios/form.html', {'form': form})

    def post(self, request, pk=None):
        form = TerritorioForm(request.POST, request=request, instance=self.objeto(request, pk))
        if form.is_valid():
            with transaction.atomic():
                territorio = form.save()
                registrar_auditoria(request, 'guardar_territorio', territorio, f'Territorio {territorio.codigo}: {territorio.nombre}')
            messages.success(request, 'Territorio guardado correctamente.')
            return redirect('usuarios:territorio_lista')
        return render(request, 'usuarios/territorios/form.html', {'form': form}, status=400)
