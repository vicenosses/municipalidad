from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView

from agenda.forms import CompromisoForm
from agenda.models import Compromiso
from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa


class CompromisoListView(LoginRequiredMixin, ListView):
    model = Compromiso
    template_name = 'agenda/lista.html'
    context_object_name = 'compromisos'

    def get_queryset(self):
        qs = Compromiso.objects.select_related('responsable', 'delegacion')
        rol = obtener_rol(self.request.user)
        if rol == 'administrador':
            return qs
        delegacion = get_delegacion_activa(self.request)
        if delegacion:
            return qs.filter(delegacion=delegacion)
        if rol == 'coordinador':
            return qs.none()
        return qs.filter(responsable=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ahora = timezone.now()
        qs = self.get_queryset()
        context['vencidos'] = [c for c in qs if c.esta_vencido]
        context['proximos'] = qs.filter(
            estado=Compromiso.Estado.PENDIENTE,
            fecha_hora__gte=ahora,
            fecha_hora__lte=ahora + timedelta(days=7),
        )
        return context


class CompromisoCreateView(RolRequiredMixin, CreateView):
    form_class = CompromisoForm
    template_name = 'agenda/form.html'
    success_url = reverse_lazy('agenda:lista')
    roles_permitidos = ('administrador', 'coordinador', 'delegado')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['delegacion'] = get_delegacion_activa(self.request)
        return kwargs

    def form_valid(self, form):
        delegacion = get_delegacion_activa(self.request)
        if delegacion is None:
            form.add_error(None, 'Su perfil no tiene una delegación asignada.')
            return self.form_invalid(form)
        form.instance.delegacion = delegacion
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Alta de compromiso: {form.instance.titulo}',
        )
        messages.success(self.request, 'Compromiso registrado en la agenda.')
        return response
