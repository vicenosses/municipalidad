from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, ListView
from django import forms

from sgr.aportes import (
    ROLES_VALIDACION, aportes_visibles, indicadores_para_actividad, pendientes_validacion,
    puede_proponer, puede_revisar, proponer_aporte, validar_aporte,
)
from sgr.forms_aportes import PropuestaAporteForm, ValidacionAporteForm
from sgr.models import AporteIndicador
from usuarios.mixins import RolRequiredMixin
from usuarios.sesion import get_delegacion_activa


class IndicadoresActividadView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador')

    def get(self, request):
        try:
            fecha = forms.DateField().clean(request.GET.get('fecha'))
        except ValidationError:
            return JsonResponse({'indicadores': []}, status=400)
        qs = indicadores_para_actividad(fecha, get_delegacion_activa(request))
        return JsonResponse({'indicadores': [{'id': i.pk, 'nombre': f'{i.nombre} · {i.meta}'} for i in qs]})


class PropuestaAporteView(RolRequiredMixin, FormView):
    roles_permitidos = ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador')
    template_name = 'sgr/aportes/propuesta.html'
    form_class = PropuestaAporteForm

    def get_actividad(self):
        if not hasattr(self, '_actividad'):
            from atenciones.views import queryset_atenciones
            self._actividad = get_object_or_404(queryset_atenciones(self.request), pk=self.kwargs['actividad_pk'])
            self.aporte = AporteIndicador.objects.filter(actividad=self._actividad).first()
            if not puede_proponer(self.request, self._actividad, self.aporte):
                raise PermissionDenied('No puede modificar este aporte. Revise el plazo y la corrección autorizada.')
        return self._actividad

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(actividad=self.get_actividad(), aporte=self.aporte)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(actividad=self.get_actividad(), aporte=self.aporte)
        return context

    def form_valid(self, form):
        try:
            proponer_aporte(self.request, self.get_actividad(), **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Aporte enviado a validación.')
        return redirect('atenciones:detalle', pk=self.get_actividad().pk)


class PendientesAporteView(RolRequiredMixin, ListView):
    roles_permitidos = ROLES_VALIDACION
    template_name = 'sgr/aportes/pendientes.html'
    context_object_name = 'aportes'
    paginate_by = 50

    def get_queryset(self):
        return pendientes_validacion(self.request)


class ValidacionAporteView(RolRequiredMixin, FormView):
    roles_permitidos = ROLES_VALIDACION
    template_name = 'sgr/aportes/validar.html'
    form_class = ValidacionAporteForm

    def get_aporte(self):
        if not hasattr(self, '_aporte'):
            self._aporte = get_object_or_404(aportes_visibles(self.request), pk=self.kwargs['pk'])
            if not puede_revisar(self.request, self._aporte):
                raise PermissionDenied('No puede autovalidar ni revisar este aporte.')
        return self._aporte

    def get_initial(self):
        return {'version': self.get_aporte().version}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['aporte'] = self.get_aporte()
        return context

    def form_valid(self, form):
        try:
            validar_aporte(self.request, self.get_aporte().pk, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Decisión del aporte registrada.')
        return redirect('atenciones:detalle', pk=self.get_aporte().actividad_id)
