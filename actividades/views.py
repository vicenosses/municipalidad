from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from actividades.forms import ActividadForm
from actividades.models import Actividad
from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol


class ActividadListView(LoginRequiredMixin, ListView):
    model = Actividad
    template_name = 'actividades/lista.html'
    context_object_name = 'actividades'

    def get_queryset(self):
        qs = Actividad.objects.select_related('funcionario', 'delegacion')
        rol = obtener_rol(self.request.user)
        if rol in ('administrador', 'coordinador', 'verificador'):
            return qs
        perfil = getattr(self.request.user, 'perfil', None)
        if perfil and perfil.delegacion_id:
            return qs.filter(delegacion=perfil.delegacion)
        return qs.filter(funcionario=self.request.user)


class ActividadCreateView(RolRequiredMixin, CreateView):
    form_class = ActividadForm
    template_name = 'actividades/form.html'
    success_url = reverse_lazy('actividades:lista')
    roles_permitidos = ('administrador', 'coordinador', 'funcionario', 'delegado')

    def form_valid(self, form):
        perfil = getattr(self.request.user, 'perfil', None)
        delegacion = perfil.delegacion if perfil else None
        if delegacion is None:
            form.add_error(None, 'Su perfil no tiene una delegación asignada.')
            return self.form_invalid(form)
        form.instance.funcionario = self.request.user
        form.instance.delegacion = delegacion
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Registro de actividad: {form.instance.titulo}',
        )
        messages.success(self.request, 'Actividad registrada.')
        return response
