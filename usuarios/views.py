from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from config.listado import FiltroExportMixin
from usuarios.forms import DelegacionForm, RolForm, UsuarioEditarForm, UsuarioMunicipalForm
from usuarios.mixins import RolRequiredMixin
from usuarios.models import Delegacion, Perfil, Rol
from usuarios.sesion import DELEGACION_SESION, delegaciones_autorizadas


class UsuarioListView(FiltroExportMixin, RolRequiredMixin, ListView):
    model = Perfil
    template_name = 'usuarios/lista.html'
    context_object_name = 'perfiles'
    roles_permitidos = ('administrador',)
    search_fields = (
        'usuario__username',
        'usuario__first_name',
        'usuario__last_name',
        'usuario__email',
        'rol__nombre',
        'delegacion__nombre',
        'delegaciones__nombre',
    )
    export_filename = 'usuarios.xlsx'
    export_headers = ('Usuario', 'Nombre', 'Correo', 'Rol', 'Delegaciones autorizadas', 'Estado')
    export_fields = (
        'usuario.username',
        'usuario.get_full_name',
        'usuario.email',
        'rol.nombre',
        'delegaciones_display',
        'estado_display',
    )

    def get_queryset(self):
        qs = Perfil.objects.select_related('usuario', 'rol', 'delegacion').prefetch_related('delegaciones')
        return self.filtrar_queryset(qs).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resumen_roles'] = (
            Perfil.objects.values('rol__nombre').annotate(total=Count('id')).order_by('rol__nombre')
        )
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


class UsuarioDetailView(RolRequiredMixin, DetailView):
    model = Perfil
    template_name = 'usuarios/detalle.html'
    context_object_name = 'perfil'
    roles_permitidos = ('administrador',)


class UsuarioUpdateView(RolRequiredMixin, UpdateView):
    model = User
    form_class = UsuarioEditarForm
    template_name = 'usuarios/form.html'
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def get_object(self, queryset=None):
        perfil = get_object_or_404(Perfil, pk=self.kwargs['pk'])
        return perfil.usuario

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'editar',
            form.instance,
            f'Edición de usuario {form.instance.username}',
        )
        messages.success(self.request, 'Usuario actualizado.')
        return response


class UsuarioDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def post(self, request, pk):
        perfil = get_object_or_404(Perfil, pk=pk)
        perfil.activo = False
        perfil.save(update_fields=['activo'])
        perfil.usuario.is_active = False
        perfil.usuario.save(update_fields=['is_active'])
        registrar_auditoria(request, 'desactivar', perfil.usuario, f'Desactivación de {perfil.usuario.username}')
        messages.success(request, 'Usuario desactivado.')
        return redirect('usuarios:lista')


class DelegacionActivaView(LoginRequiredMixin, View):
    def post(self, request):
        pk = request.POST.get('delegacion_id')
        autorizadas = delegaciones_autorizadas(request.user)
        if autorizadas.filter(pk=pk).exists():
            request.session[DELEGACION_SESION] = int(pk)
            messages.success(request, 'Delegación activa actualizada.')
        return redirect(request.META.get('HTTP_REFERER') or 'home')


class DelegacionListView(FiltroExportMixin, RolRequiredMixin, ListView):
    model = Delegacion
    template_name = 'usuarios/delegaciones/lista.html'
    context_object_name = 'delegaciones'
    roles_permitidos = ('administrador', 'coordinador')
    search_fields = ('codigo', 'nombre', 'direccion', 'comuna')
    export_filename = 'delegaciones.xlsx'
    export_headers = ('Código', 'Nombre', 'Dirección', 'Comuna', 'Estado')
    export_fields = ('codigo', 'nombre', 'direccion', 'comuna', 'estado_display')


class DelegacionCreateView(RolRequiredMixin, CreateView):
    model = Delegacion
    form_class = DelegacionForm
    template_name = 'usuarios/delegaciones/form.html'
    success_url = reverse_lazy('usuarios:delegacion_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de delegación {form.instance.nombre}')
        messages.success(self.request, 'Delegación registrada.')
        return response


class DelegacionDetailView(RolRequiredMixin, DetailView):
    model = Delegacion
    template_name = 'usuarios/delegaciones/detalle.html'
    roles_permitidos = ('administrador', 'coordinador')


class DelegacionUpdateView(RolRequiredMixin, UpdateView):
    model = Delegacion
    form_class = DelegacionForm
    template_name = 'usuarios/delegaciones/form.html'
    success_url = reverse_lazy('usuarios:delegacion_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de delegación {form.instance.nombre}')
        messages.success(self.request, 'Delegación actualizada.')
        return response


class DelegacionDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador')

    def post(self, request, pk):
        obj = get_object_or_404(Delegacion, pk=pk)
        obj.activa = False
        obj.save(update_fields=['activa'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de delegación {obj.nombre}')
        messages.success(request, 'Delegación desactivada.')
        return redirect('usuarios:delegacion_lista')


class RolListView(FiltroExportMixin, RolRequiredMixin, ListView):
    model = Rol
    template_name = 'usuarios/roles/lista.html'
    context_object_name = 'roles'
    roles_permitidos = ('administrador',)
    search_fields = ('codigo', 'nombre', 'descripcion', 'alcance')
    export_filename = 'roles.xlsx'
    export_headers = ('Código', 'Nombre', 'Descripción', 'Alcance', 'Estado')
    export_fields = ('codigo', 'nombre', 'descripcion', 'get_alcance_display', 'estado_display')


class RolCreateView(RolRequiredMixin, CreateView):
    model = Rol
    form_class = RolForm
    template_name = 'usuarios/roles/form.html'
    success_url = reverse_lazy('usuarios:rol_lista')
    roles_permitidos = ('administrador',)

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de rol {form.instance.nombre}')
        messages.success(self.request, 'Rol registrado.')
        return response


class RolDetailView(RolRequiredMixin, DetailView):
    model = Rol
    template_name = 'usuarios/roles/detalle.html'
    roles_permitidos = ('administrador',)


class RolUpdateView(RolRequiredMixin, UpdateView):
    model = Rol
    form_class = RolForm
    template_name = 'usuarios/roles/form.html'
    success_url = reverse_lazy('usuarios:rol_lista')
    roles_permitidos = ('administrador',)

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de rol {form.instance.nombre}')
        messages.success(self.request, 'Rol actualizado.')
        return response


class RolDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def post(self, request, pk):
        obj = get_object_or_404(Rol, pk=pk)
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de rol {obj.nombre}')
        messages.success(request, 'Rol desactivado.')
        return redirect('usuarios:rol_lista')
