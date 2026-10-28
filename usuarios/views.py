from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from config.listado import FiltroExportMixin
from usuarios.forms import (
    DecisionTransferenciaForm,
    CargoForm,
    DelegacionForm,
    RolForm,
    SolicitudTransferenciaForm,
    TransferenciaDirectaForm,
    UsuarioEditarForm,
    UsuarioMunicipalForm,
)
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.models import Cargo, Delegacion, Perfil, Rol, SolicitudTransferencia
from usuarios.sesion import CONTEXTO_GLOBAL, DELEGACION_SESION, delegaciones_autorizadas
from usuarios.sesion import get_delegacion_activa, usuario_tiene_alcance_delegacion
from usuarios.sesion import en_contexto_delegacion, filtrar_contexto_territorial
from usuarios.transferencias import (
    CompromisosPendientesError,
    aplicar_transferencia,
    contar_compromisos_activos,
)


def perfiles_en_contexto(request):
    return filtrar_contexto_territorial(Perfil.objects.select_related(
        'usuario', 'rol', 'delegacion').prefetch_related('delegaciones'), request,
        campo='delegaciones').distinct()


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
        qs = perfiles_en_contexto(self.request)
        return self.filtrar_queryset(qs).distinct().annotate(
            orden_inactivo=Case(When(activo=True, usuario__is_active=True, then=Value(0)), default=Value(1), output_field=IntegerField())
        ).order_by('orden_inactivo', 'usuario__username', 'pk')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resumen_roles'] = (
            perfiles_en_contexto(self.request).values('rol__nombre').annotate(total=Count('id')).order_by('rol__nombre')
        )
        return context


class UsuarioCreateView(RolRequiredMixin, CreateView):
    form_class = UsuarioMunicipalForm
    template_name = 'usuarios/form.html'
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        delegacion = get_delegacion_activa(self.request)
        if delegacion is not None:
            form.fields['delegaciones'].queryset = Delegacion.objects.filter(pk=delegacion.pk)
            form.fields['delegaciones'].initial = [delegacion.pk]
        return form

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

    def get_queryset(self):
        return perfiles_en_contexto(self.request)


class UsuarioUpdateView(RolRequiredMixin, UpdateView):
    model = User
    form_class = UsuarioEditarForm
    template_name = 'usuarios/form.html'
    success_url = reverse_lazy('usuarios:lista')
    roles_permitidos = ('administrador',)

    def get_object(self, queryset=None):
        perfil = get_object_or_404(perfiles_en_contexto(self.request), pk=self.kwargs['pk'])
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
        perfil = get_object_or_404(perfiles_en_contexto(request), pk=pk)
        perfil.activo = request.POST.get('activo') == 'true'
        perfil.save(update_fields=['activo'])
        perfil.usuario.is_active = perfil.activo
        perfil.usuario.save(update_fields=['is_active'])
        registrar_auditoria(request, 'activar' if perfil.activo else 'desactivar', perfil.usuario, f'Cambio de estado de {perfil.usuario.username}')
        messages.success(request, 'Usuario activado.' if perfil.activo else 'Usuario desactivado.')
        return redirect('usuarios:lista')


class TransferenciasView(RolRequiredMixin, ListView):
    model = SolicitudTransferencia
    template_name = 'usuarios/transferencias/lista.html'
    context_object_name = 'solicitudes'
    roles_permitidos = ('administrador', 'delegado', 'coordinador')

    def get_queryset(self):
        queryset = SolicitudTransferencia.objects.select_related(
            'usuario',
            'delegacion_origen',
            'delegacion_destino',
            'solicitante',
            'decidido_por',
        )
        rol = obtener_rol(self.request.user)
        if rol == 'administrador':
            return filtrar_contexto_territorial(queryset, self.request, 'delegacion_origen')
        if rol == 'coordinador':
            return filtrar_contexto_territorial(queryset, self.request, 'delegacion_origen').filter(
                solicitante=self.request.user)
        delegacion = get_delegacion_activa(self.request)
        if delegacion is None:
            return queryset.none()
        return queryset.filter(delegacion_origen=delegacion)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rol = obtener_rol(self.request.user)
        delegacion = get_delegacion_activa(self.request)
        context['rol_transferencia'] = rol
        context['delegacion_activa'] = delegacion
        perfiles = Perfil.objects.select_related('usuario', 'delegacion', 'rol')
        if rol == 'delegado':
            perfiles = perfiles.filter(
                delegacion=delegacion,
                delegaciones=delegacion,
            ) if delegacion is not None else perfiles.none()
        elif rol == 'administrador':
            perfiles = filtrar_contexto_territorial(perfiles, self.request).exclude(delegacion__isnull=True).filter(
                delegaciones=F('delegacion'),
            )
        else:
            perfiles = Perfil.objects.none()
        context['perfiles_transferibles'] = perfiles.order_by(
            'usuario__last_name',
            'usuario__first_name',
            'usuario__username',
        )
        return context


class SolicitudTransferenciaCreateView(RolRequiredMixin, View):
    template_name = 'usuarios/transferencias/solicitar.html'
    roles_permitidos = ('coordinador',)

    def delegacion_origen(self):
        return get_delegacion_activa(self.request)

    def get(self, request):
        origen = self.delegacion_origen()
        if origen is None:
            raise PermissionDenied('Debe tener una delegación activa para solicitar una transferencia.')
        return self.render_form(SolicitudTransferenciaForm(delegacion_origen=origen), origen)

    @transaction.atomic
    def post(self, request):
        origen = self.delegacion_origen()
        if origen is None:
            raise PermissionDenied('Debe tener una delegación activa para solicitar una transferencia.')
        form = SolicitudTransferenciaForm(
            request.POST,
            delegacion_origen=origen,
        )
        if not form.is_valid():
            return self.render_form(form, origen)

        usuario = form.cleaned_data['usuario']
        solicitud = SolicitudTransferencia(
            usuario=usuario,
            delegacion_origen=origen,
            delegacion_destino=form.cleaned_data['delegacion_destino'],
            solicitante=request.user,
            motivo=form.cleaned_data['motivo'],
        )
        try:
            solicitud.full_clean()
            solicitud.save()
        except ValidationError as error:
            form.add_error(None, error)
            return self.render_form(form, origen)

        registrar_auditoria(
            request,
            'solicitar_transferencia',
            solicitud,
            (
                f'Solicitud de transferencia de {usuario.get_full_name() or usuario.username}: '
                f'{origen.nombre} → {solicitud.delegacion_destino.nombre}'
            ),
        )
        messages.success(request, 'Solicitud de transferencia enviada.')
        return redirect('usuarios:transferencias')

    def render_form(self, form, origen):
        return render(
            self.request,
            self.template_name,
            {'form': form, 'delegacion_origen': origen},
        )


class TransferenciaDirectaView(RolRequiredMixin, View):
    template_name = 'usuarios/transferencias/transferir.html'
    roles_permitidos = ('administrador', 'delegado')

    def get_usuario_origen(self, request, pk):
        perfil = get_object_or_404(
            Perfil.objects.select_related('usuario', 'delegacion'),
            usuario_id=pk,
        )
        rol = obtener_rol(request.user)
        if perfil.delegacion_id is None:
            raise PermissionDenied('El usuario no tiene una delegación de origen definida.')
        if not en_contexto_delegacion(request, perfil.delegacion):
            raise PermissionDenied('El usuario no pertenece al contexto territorial activo.')
        if rol == 'delegado':
            activa = get_delegacion_activa(request)
            if (
                activa is None
                or activa.pk != perfil.delegacion_id
                or not usuario_tiene_alcance_delegacion(request.user, activa)
            ):
                raise PermissionDenied('Solo puede transferir usuarios de su delegación activa.')
        if not perfil.delegaciones.filter(pk=perfil.delegacion_id).exists():
            raise PermissionDenied('El usuario no está autorizado en su delegación de origen.')
        return perfil.usuario, perfil.delegacion

    def get(self, request, pk):
        usuario, origen = self.get_usuario_origen(request, pk)
        form = TransferenciaDirectaForm(delegacion_origen=origen)
        return self.render_form(request, usuario, origen, form)

    @transaction.atomic
    def post(self, request, pk):
        usuario, origen = self.get_usuario_origen(request, pk)
        form = TransferenciaDirectaForm(
            request.POST,
            delegacion_origen=origen,
        )
        if not form.is_valid():
            return self.render_form(request, usuario, origen, form)
        destino = form.cleaned_data['delegacion_destino']
        try:
            cantidad = aplicar_transferencia(
                usuario,
                origen,
                destino,
                form.cleaned_data['confirmar_compromisos'],
            )
        except CompromisosPendientesError as error:
            form.add_error('confirmar_compromisos', error)
            return self.render_form(request, usuario, origen, form)
        except ValidationError as error:
            form.add_error(None, error)
            return self.render_form(request, usuario, origen, form)

        registrar_auditoria(
            request,
            'transferencia_directa',
            usuario,
            (
                f'Transferencia de {usuario.get_full_name() or usuario.username}: '
                f'{origen.nombre} → {destino.nombre}. '
                f'Compromisos activos al transferir: {cantidad}. '
                f'Observación: {form.cleaned_data["motivo"] or "—"}'
            ),
        )
        messages.success(request, 'Transferencia realizada. Los compromisos no fueron reasignados.')
        return redirect('usuarios:transferencias')

    def render_form(self, request, usuario, origen, form):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'usuario_transferido': usuario,
                'delegacion_origen': origen,
                'compromisos_activos': contar_compromisos_activos(usuario),
            },
        )


class TransferenciaDecisionView(RolRequiredMixin, View):
    template_name = 'usuarios/transferencias/decidir.html'
    roles_permitidos = ('administrador', 'delegado')

    def get_solicitud(self, request, pk, lock=False):
        queryset = SolicitudTransferencia.objects.select_related(
            'usuario',
            'delegacion_origen',
            'delegacion_destino',
            'solicitante',
        )
        queryset = filtrar_contexto_territorial(queryset, request, 'delegacion_origen')
        if obtener_rol(request.user) == 'delegado':
            origen = get_delegacion_activa(request)
            if origen is None:
                raise PermissionDenied('Debe tener una delegación activa.')
            queryset = queryset.filter(delegacion_origen=origen)
        if lock:
            queryset = queryset.select_for_update()
        return get_object_or_404(queryset, pk=pk)

    def get(self, request, pk):
        solicitud = self.get_solicitud(request, pk)
        return self.render_form(
            request,
            solicitud,
            DecisionTransferenciaForm(),
        )

    @transaction.atomic
    def post(self, request, pk):
        solicitud = self.get_solicitud(request, pk, lock=True)
        form = DecisionTransferenciaForm(request.POST)
        if not form.is_valid():
            return self.render_form(request, solicitud, form)
        if solicitud.estado != SolicitudTransferencia.Estado.PENDIENTE:
            form.add_error(None, 'La solicitud ya fue resuelta.')
            return self.render_form(request, solicitud, form)
        if solicitud.solicitante_id == request.user.pk:
            form.add_error(None, 'No puede decidir una solicitud propia.')
            return self.render_form(request, solicitud, form)

        accion = form.cleaned_data['accion']
        if accion == 'aprobar':
            try:
                cantidad = aplicar_transferencia(
                    solicitud.usuario,
                    solicitud.delegacion_origen,
                    solicitud.delegacion_destino,
                    form.cleaned_data['confirmar_compromisos'],
                )
            except CompromisosPendientesError as error:
                form.add_error('confirmar_compromisos', error)
                return self.render_form(request, solicitud, form)
            except (ValidationError, Perfil.DoesNotExist) as error:
                form.add_error(None, error)
                return self.render_form(request, solicitud, form)
            solicitud.estado = SolicitudTransferencia.Estado.APROBADA
            accion_auditoria = 'aprobar_transferencia'
            texto = (
                f'Transferencia aprobada para {solicitud.usuario.get_full_name() or solicitud.usuario.username}: '
                f'{solicitud.delegacion_origen.nombre} → {solicitud.delegacion_destino.nombre}. '
                f'Compromisos activos al aprobar: {cantidad}.'
            )
        else:
            solicitud.estado = SolicitudTransferencia.Estado.RECHAZADA
            accion_auditoria = 'rechazar_transferencia'
            texto = (
                f'Transferencia rechazada para {solicitud.usuario.get_full_name() or solicitud.usuario.username}: '
                f'{solicitud.delegacion_origen.nombre} → {solicitud.delegacion_destino.nombre}.'
            )
        solicitud.decidido_por = request.user
        solicitud.fecha_decision = timezone.now()
        solicitud.observacion_decision = form.cleaned_data['observacion_decision']
        solicitud.save(
            update_fields=[
                'estado',
                'decidido_por',
                'fecha_decision',
                'observacion_decision',
            ]
        )
        registrar_auditoria(request, accion_auditoria, solicitud, texto)
        messages.success(
            request,
            'Solicitud aprobada.' if accion == 'aprobar' else 'Solicitud rechazada.',
        )
        return redirect('usuarios:transferencias')

    def render_form(self, request, solicitud, form):
        return render(
            request,
            self.template_name,
            {
                'form': form,
                'solicitud': solicitud,
                'compromisos_activos': contar_compromisos_activos(solicitud.usuario),
            },
        )


class DelegacionActivaView(LoginRequiredMixin, View):
    def post(self, request):
        if obtener_rol(request.user) != 'administrador':
            raise PermissionDenied('Solo el Administrador puede cambiar el contexto territorial.')
        valor = request.POST.get('delegacion_id')
        if valor == CONTEXTO_GLOBAL:
            request.session[DELEGACION_SESION] = CONTEXTO_GLOBAL
            etiqueta = 'Global: todas las delegaciones'
        else:
            try:
                pk = int(valor)
            except (TypeError, ValueError):
                return HttpResponseBadRequest('Seleccione una delegación válida o el contexto global.')
            delegacion = delegaciones_autorizadas(request.user).filter(pk=pk).first()
            if delegacion is None:
                return HttpResponseBadRequest('La delegación no existe o está inactiva.')
            request.session[DELEGACION_SESION] = delegacion.pk
            etiqueta = str(delegacion)
        messages.success(request, f'Contexto territorial actualizado: {etiqueta}.')
        destino = request.POST.get('next') or request.META.get('HTTP_REFERER')
        if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            return HttpResponseRedirect(destino)
        return redirect('home')


class DelegacionListView(FiltroExportMixin, RolRequiredMixin, ListView):
    ordering = ('-activa', 'nombre', 'pk')
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
        obj.activa = request.POST.get('activo') == 'true'
        obj.save(update_fields=['activa'])
        registrar_auditoria(request, 'activar' if obj.activa else 'desactivar', obj, f'Cambio de estado de delegación {obj.nombre}')
        messages.success(request, 'Delegación activada.' if obj.activa else 'Delegación desactivada.')
        return redirect('usuarios:delegacion_lista')


class CargoListView(FiltroExportMixin, RolRequiredMixin, ListView):
    ordering = ('-activo', 'nombre', 'pk')
    model = Cargo
    template_name = 'usuarios/cargos/lista.html'
    context_object_name = 'cargos'
    roles_permitidos = ('administrador',)
    search_fields = ('nombre', 'descripcion')
    export_filename = 'cargos.xlsx'
    export_headers = ('Cargo', 'Descripción', 'Alcance', 'Estado')
    export_fields = ('nombre', 'descripcion', 'get_alcance_display', 'activo')


class CargoCreateView(RolRequiredMixin, CreateView):
    form_class = CargoForm
    template_name = 'usuarios/cargos/form.html'
    success_url = reverse_lazy('usuarios:cargo_lista')
    roles_permitidos = ('administrador',)

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', self.object, f'Alta de cargo {self.object.nombre}')
        messages.success(self.request, 'Cargo creado correctamente.')
        return response


class CargoDetailView(RolRequiredMixin, DetailView):
    model = Cargo
    template_name = 'usuarios/cargos/detalle.html'
    roles_permitidos = ('administrador',)


class CargoUpdateView(RolRequiredMixin, UpdateView):
    model = Cargo
    form_class = CargoForm
    template_name = 'usuarios/cargos/form.html'
    success_url = reverse_lazy('usuarios:cargo_lista')
    roles_permitidos = ('administrador',)

    @transaction.atomic
    def form_valid(self, form):
        nombre_anterior = Cargo.objects.select_for_update().get(pk=self.object.pk).nombre
        response = super().form_valid(form)
        if nombre_anterior != self.object.nombre:
            Perfil.objects.filter(cargo=nombre_anterior).update(cargo=self.object.nombre)
        registrar_auditoria(self.request, 'editar', self.object, f'Edición de cargo {nombre_anterior} → {self.object.nombre}')
        messages.success(self.request, 'Cargo actualizado.')
        return response


class CargoEstadoView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def post(self, request, pk):
        cargo = get_object_or_404(Cargo, pk=pk)
        valor = request.POST.get('activo')
        if valor not in ('true', 'false'):
            return HttpResponseBadRequest('Estado no válido.')
        cargo.activo = valor == 'true'
        cargo.save(update_fields=['activo'])
        registrar_auditoria(request, 'activar' if cargo.activo else 'desactivar', cargo, f'Cambio de estado de cargo {cargo.nombre}')
        messages.success(request, 'Cargo activado.' if cargo.activo else 'Cargo desactivado.')
        return redirect('usuarios:cargo_lista')


class RolListView(FiltroExportMixin, RolRequiredMixin, ListView):
    ordering = ('-activo', 'nombre', 'pk')
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
        obj.activo = request.POST.get('activo') == 'true'
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'activar' if obj.activo else 'desactivar', obj, f'Cambio de estado de rol {obj.nombre}')
        messages.success(request, 'Rol activado.' if obj.activo else 'Rol desactivado.')
        return redirect('usuarios:rol_lista')
