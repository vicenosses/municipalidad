from django.contrib import messages
from django.db.models import Count
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from usuarios.forms import DelegacionForm, PerfilRolForm, UsuarioMunicipalForm
from usuarios.mixins import RolRequiredMixin
from usuarios.models import Delegacion, Perfil


class UsuarioListView(RolRequiredMixin, ListView):
    model = Perfil
    template_name = 'usuarios/lista.html'
    context_object_name = 'perfiles'
    roles_permitidos = ('administrador',)

    def get_queryset(self):
        return Perfil.objects.select_related('usuario', 'delegacion')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resumen_roles'] = (
            Perfil.objects.values('rol').annotate(total=Count('id')).order_by('rol')
        )
        context['roles'] = Perfil.Rol
        context['delegacion_form'] = DelegacionForm()
        context['delegaciones'] = Delegacion.objects.all()
        return context


class UsuarioCreateView(RolRequiredMixin, CreateView):
    form_class = UsuarioMunicipalForm
    template_name = 'usuarios/form.html'
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Alta de usuario {form.instance.username}',
        )
        messages.success(self.request, 'Usuario creado correctamente.')
        return response


class PerfilUpdateView(RolRequiredMixin, UpdateView):
    model = Perfil
    form_class = PerfilRolForm
    template_name = 'usuarios/perfil_form.html'
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'editar',
            form.instance,
            f'Actualización de rol/delegación de {form.instance.usuario.username}',
        )
        messages.success(self.request, 'Perfil actualizado.')
        return response


class DelegacionCreateView(RolRequiredMixin, CreateView):
    model = Delegacion
    form_class = DelegacionForm
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def get(self, request, *args, **kwargs):
        return redirect('usuarios:lista')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Alta de delegación {form.instance.nombre}',
        )
        messages.success(self.request, 'Delegación registrada.')
        return response
