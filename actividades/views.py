from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from actividades.forms import ActividadForm
from actividades.models import Actividad
from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa


class ActividadListView(LoginRequiredMixin, ListView):
    model = Actividad
    template_name = 'actividades/lista.html'
    context_object_name = 'actividades'

    def get_queryset(self):
        qs = Actividad.objects.select_related('funcionario', 'delegacion')
        rol = obtener_rol(self.request.user)
        if rol == 'administrador':
            return qs
        delegacion = get_delegacion_activa(self.request)
        if delegacion:
            return qs.filter(delegacion=delegacion)
        if rol in ('coordinador', 'verificador'):
            return qs.none()
        return qs.filter(funcionario=self.request.user)


class ActividadCreateView(RolRequiredMixin, CreateView):
    form_class = ActividadForm
    template_name = 'actividades/form.html'
    success_url = reverse_lazy('actividades:lista')
    roles_permitidos = ('administrador', 'coordinador', 'funcionario', 'delegado')

    def form_valid(self, form):
        delegacion = get_delegacion_activa(self.request)
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
