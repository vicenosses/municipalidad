from django.views.generic import ListView

from auditoria.forms import AuditoriaFiltroForm
from auditoria.models import RegistroAuditoria
from usuarios.mixins import RolRequiredMixin


class AuditoriaListView(RolRequiredMixin, ListView):
    model = RegistroAuditoria
    template_name = 'auditoria/lista.html'
    context_object_name = 'registros'
    paginate_by = 50
    roles_permitidos = ('administrador', 'coordinador')

    def get_filtro_form(self):
        if not hasattr(self, '_filtro_form'):
            self._filtro_form = AuditoriaFiltroForm(
                data=self.request.GET if self.request.GET else None
            )
        return self._filtro_form

    def get_queryset(self):
        qs = RegistroAuditoria.objects.select_related('usuario')
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
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.get_filtro_form()
        context['query_params'] = self.request.GET.urlencode()
        return context
