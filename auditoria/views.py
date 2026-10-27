from django.views.generic import ListView
from django.db.models import Q

from auditoria.forms import AuditoriaFiltroForm
from auditoria.models import RegistroAuditoria
from auditoria.permisos import registros_autorizados
from auditoria.presentacion import MODULOS, presentar_registros
from usuarios.mixins import RolRequiredMixin


class AuditoriaListView(RolRequiredMixin, ListView):
    model = RegistroAuditoria
    template_name = 'auditoria/lista.html'
    context_object_name = 'registros'
    paginate_by = 50
    roles_permitidos = ('administrador', 'delegado', 'coordinador')

    def get_registros_autorizados(self):
        if not hasattr(self, '_registros_autorizados'):
            self._registros_autorizados = registros_autorizados(
                self.request, RegistroAuditoria.objects.select_related('usuario')
            ).order_by('-timestamp', '-pk')
        return self._registros_autorizados

    def get_filtro_form(self):
        if not hasattr(self, '_filtro_form'):
            self._filtro_form = AuditoriaFiltroForm(
                data=self.request.GET if self.request.GET else None,
                registros=self.get_registros_autorizados(),
            )
        return self._filtro_form

    def get_queryset(self):
        qs = self.get_registros_autorizados()
        form = self.get_filtro_form()
        if not form.is_bound:
            return qs
        if not form.is_valid():
            return qs.none()
        if form.cleaned_data['usuario']:
            qs = qs.filter(usuario=form.cleaned_data['usuario'])
        if form.cleaned_data['fecha_desde']:
            qs = qs.filter(timestamp__date__gte=form.cleaned_data['fecha_desde'])
        if form.cleaned_data['fecha_hasta']:
            qs = qs.filter(timestamp__date__lte=form.cleaned_data['fecha_hasta'])
        if form.cleaned_data['accion']:
            qs = qs.filter(accion=form.cleaned_data['accion'])
        if form.cleaned_data['modulo']:
            qs = qs.filter(modelo__in=MODULOS[form.cleaned_data['modulo']][1])
        if form.cleaned_data['buscar']:
            texto = form.cleaned_data['buscar']
            qs = qs.filter(Q(descripcion__icontains=texto) | Q(accion__icontains=texto)
                           | Q(objeto_id__icontains=texto))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.get_filtro_form()
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context['query_params'] = parametros.urlencode()
        context['registros'] = presentar_registros(list(context['registros']))
        return context
