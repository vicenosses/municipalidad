from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from atenciones.forms import AtencionCiudadanaForm
from atenciones.models import AtencionCiudadana
from auditoria.utils import registrar_auditoria
from config.listado import FiltroExportMixin
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa


def queryset_atenciones(request):
    qs = AtencionCiudadana.objects.select_related(
        'tipo', 'subatencion', 'delegacion', 'responsable'
    )
    rol = obtener_rol(request.user)
    if rol in ('administrador', 'coordinador', 'verificador'):
        return qs
    delegacion = get_delegacion_activa(request)
    if delegacion:
        return qs.filter(delegacion=delegacion)
    return qs.filter(responsable=request.user)


class AtencionListView(FiltroExportMixin, LoginRequiredMixin, ListView):
    model = AtencionCiudadana
    template_name = 'atenciones/lista.html'
    context_object_name = 'atenciones'
    search_fields = (
        'solicitante',
        'descripcion',
        'tipo__nombre',
        'subatencion__nombre',
        'delegacion__nombre',
        'responsable__username',
    )
    export_filename = 'atenciones.xlsx'
    export_headers = ('Fecha', 'Solicitante', 'Tipo', 'Subatención', 'Delegación', 'Responsable')
    export_fields = (
        'fecha_registro',
        'solicitante',
        'tipo.nombre',
        'subatencion.nombre',
        'delegacion.nombre',
        'responsable.get_full_name',
    )

    def get_queryset(self):
        return self.filtrar_queryset(queryset_atenciones(self.request))


class AtencionDetailView(LoginRequiredMixin, DetailView):
    model = AtencionCiudadana
    template_name = 'atenciones/detalle.html'
    context_object_name = 'atencion'

    def get_queryset(self):
        return queryset_atenciones(self.request)


class AtencionCreateView(RolRequiredMixin, CreateView):
    form_class = AtencionCiudadanaForm
    template_name = 'atenciones/form.html'
    success_url = reverse_lazy('atenciones:lista')
    roles_permitidos = ('administrador', 'coordinador', 'funcionario', 'delegado', 'verificador')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['delegacion_activa'] = get_delegacion_activa(self.request)
        context['subatenciones'] = list(
            context['form'].fields['subatencion'].queryset.values('id', 'tipo_id')
        )
        return context

    def form_valid(self, form):
        delegacion = get_delegacion_activa(self.request)
        if delegacion is None:
            form.add_error(None, 'Debe tener una delegación activa para registrar la atención.')
            return self.form_invalid(form)
        form.instance.delegacion = delegacion
        form.instance.responsable = self.request.user
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Atención ciudadana de {form.instance.solicitante}',
        )
        messages.success(self.request, 'Atención ciudadana registrada.')
        return response
