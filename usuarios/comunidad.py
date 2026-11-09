from django import forms
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from agenda.validaciones import validar_y_formatear_rut
from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.models import Vecino, JuntaVecinos, ParticipacionJunta, Territorio
from usuarios.sesion import filtrar_contexto_territorial, get_delegacion_activa


class VecinoForm(forms.ModelForm):
    class Meta:
        model = Vecino
        fields = ('rut', 'nombres', 'apellidos', 'telefono', 'correo', 'direccion', 'territorio', 'activo')

    def clean_rut(self):
        return validar_y_formatear_rut(self.cleaned_data['rut'])

    def clean_territorio(self):
        territorio = self.cleaned_data['territorio']
        if self.instance.pk and self.instance.participaciones.exclude(junta__territorio__delegacion=territorio.delegacion).exists():
            raise forms.ValidationError('No se puede cambiar de delegación mientras existan participaciones en juntas de la delegación anterior.')
        return territorio


class JuntaForm(forms.ModelForm):
    class Meta:
        model = JuntaVecinos
        fields = ('nombre', 'direccion', 'territorio', 'fecha_constitucion', 'activo')
        widgets = {'fecha_constitucion': forms.DateInput(attrs={'type': 'date'})}

    def clean_territorio(self):
        territorio = self.cleaned_data['territorio']
        if self.instance.pk and self.instance.participaciones.exclude(vecino__territorio__delegacion=territorio.delegacion).exists():
            raise forms.ValidationError('No se puede cambiar de delegación mientras existan vecinos vinculados a la delegación anterior.')
        return territorio


class ParticipacionForm(forms.ModelForm):
    class Meta:
        model = ParticipacionJunta
        fields = ('vecino', 'junta', 'dirigente', 'cargo', 'fecha_incorporacion', 'activo')
        widgets = {'fecha_incorporacion': forms.DateInput(attrs={'type': 'date'})}


ENTIDADES = {
    'vecinos': (Vecino, VecinoForm, 'Vecinos', 'territorio__delegacion'),
    'juntas': (JuntaVecinos, JuntaForm, 'Juntas de vecinos', 'territorio__delegacion'),
    'participaciones': (ParticipacionJunta, ParticipacionForm, 'Participaciones en juntas', 'junta__territorio__delegacion'),
}


class ComunidadView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado', 'coordinador')

    def get(self, request, tipo):
        if tipo not in ENTIDADES:
            from django.http import Http404
            raise Http404
        model, _, titulo, campo = ENTIDADES[tipo]
        registros = filtrar_contexto_territorial(model.objects.all(), request, campo=campo).order_by('-activo', '-pk')
        q = request.GET.get('q', '').strip()
        if q:
            criterios = {
                'vecinos': Q(nombres__icontains=q) | Q(apellidos__icontains=q) | Q(rut__icontains=q),
                'juntas': Q(nombre__icontains=q) | Q(codigo__icontains=q),
                'participaciones': Q(vecino__nombres__icontains=q) | Q(vecino__apellidos__icontains=q) | Q(junta__nombre__icontains=q),
            }
            registros = registros.filter(criterios[tipo])
        relaciones = {'vecinos': ('territorio',), 'juntas': ('territorio',),
                      'participaciones': ('vecino', 'junta')}
        pagina = Paginator(registros.select_related(*relaciones[tipo]), 25).get_page(request.GET.get('page'))
        parametros = request.GET.copy()
        parametros.pop('page', None)
        return render(request, 'usuarios/comunidad/lista.html', {
            'registros': pagina, 'page_obj': pagina, 'query_params': parametros.urlencode(), 'tipo': tipo, 'titulo': titulo,
            'q': q, 'puede_editar': obtener_rol(request.user) == 'administrador',
        })


class ComunidadGuardarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def gestionar(self, request, tipo, pk=None):
        if tipo not in ENTIDADES:
            from django.http import Http404
            raise Http404
        model, form_class, titulo, campo = ENTIDADES[tipo]
        qs = filtrar_contexto_territorial(model.objects.all(), request, campo=campo)
        instancia = get_object_or_404(qs, pk=pk) if pk else None
        form = form_class(request.POST or None, instance=instancia)
        delegacion = get_delegacion_activa(request)
        for campo_form, modelo, ruta in (('territorio', Territorio, 'delegacion'),
                                         ('vecino', Vecino, 'territorio__delegacion'),
                                         ('junta', JuntaVecinos, 'territorio__delegacion')):
            if campo_form in form.fields:
                valores = modelo.objects.all()
                if delegacion:
                    valores = valores.filter(**{ruta: delegacion})
                form.fields[campo_form].queryset = valores
        for campo_actual in form.fields.values():
            campo_actual.widget.attrs.setdefault('class', 'form-check-input' if isinstance(campo_actual.widget, forms.CheckboxInput) else 'form-control')
        if request.method == 'POST' and form.is_valid():
            from django.db import transaction
            with transaction.atomic():
                objeto = form.save()
                registrar_auditoria(request, 'guardar_comunidad', objeto, f'{titulo}: {objeto.pk}')
            return redirect('usuarios:comunidad_lista', tipo=tipo)
        return render(request, 'usuarios/comunidad/form.html', {'form': form, 'tipo': tipo, 'titulo': titulo}, status=400 if request.method == 'POST' else 200)

    def get(self, request, tipo, pk=None):
        return self.gestionar(request, tipo, pk)

    def post(self, request, tipo, pk=None):
        return self.gestionar(request, tipo, pk)


class ComunidadDetalleView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado', 'coordinador')

    def get(self, request, tipo, pk):
        if tipo not in ENTIDADES:
            from django.http import Http404
            raise Http404
        model, _, titulo, campo = ENTIDADES[tipo]
        registro = get_object_or_404(filtrar_contexto_territorial(model.objects.all(), request, campo=campo), pk=pk)
        return render(request, 'usuarios/comunidad/detalle.html', {'registro': registro, 'tipo': tipo, 'titulo': titulo})


class ComunidadEstadoView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def post(self, request, tipo, pk):
        from django.db import transaction
        from django.http import Http404
        if tipo not in ENTIDADES or request.POST.get('activo') not in ('true', 'false'):
            raise Http404
        model, _, titulo, campo = ENTIDADES[tipo]
        with transaction.atomic():
            qs = filtrar_contexto_territorial(model.objects.select_for_update(), request, campo=campo)
            registro = get_object_or_404(qs, pk=pk)
            registro.activo = request.POST['activo'] == 'true'
            registro.save(update_fields=['activo'])
            registrar_auditoria(request, 'estado_comunidad', registro, f'{titulo}: {registro.pk}; activo: {registro.activo}')
        return redirect('usuarios:comunidad_lista', tipo=tipo)
