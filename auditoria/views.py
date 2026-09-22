from django.contrib.auth.models import User
from django.views.generic import ListView

from auditoria.models import RegistroAuditoria
from usuarios.mixins import RolRequiredMixin


class AuditoriaListView(RolRequiredMixin, ListView):
    model = RegistroAuditoria
    template_name = 'auditoria/lista.html'
    context_object_name = 'registros'
    paginate_by = 50
    roles_permitidos = ('administrador', 'coordinador')

    def get_queryset(self):
        qs = RegistroAuditoria.objects.select_related('usuario')
        usuario_id = self.request.GET.get('usuario')
        fecha_desde = self.request.GET.get('fecha_desde')
        fecha_hasta = self.request.GET.get('fecha_hasta')
        if usuario_id:
            qs = qs.filter(usuario_id=usuario_id)
        if fecha_desde:
            qs = qs.filter(timestamp__date__gte=fecha_desde)
        if fecha_hasta:
            qs = qs.filter(timestamp__date__lte=fecha_hasta)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['usuarios'] = User.objects.order_by('username')
        context['filtros'] = self.request.GET
        return context
