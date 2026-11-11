from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from cartas.models import Carta
from gestion_social.models import GestionSocial
from hitos.models import Hito
from operaciones.forms import (
    CambioEstadoForm,
    CartaForm,
    GestionSocialForm,
    HitoForm,
    ROLES_GESTORES,
)
from usuarios.mixins import obtener_rol
from usuarios.sesion import (
    delegaciones_autorizadas,
    filtrar_contexto_territorial,
    get_delegacion_activa,
)

ROLES_VALIDOS = (*ROLES_GESTORES, 'funcionario', 'verificador')


def _puede_editar(user, objeto):
    return obtener_rol(user) in ROLES_GESTORES or objeto.responsable_id == user.pk


def _estado_terminal(objeto):
    if isinstance(objeto, Carta):
        return objeto.estado == Carta.Estado.CERRADA
    if isinstance(objeto, GestionSocial):
        return objeto.estado == GestionSocial.Estado.CERRADA
    return objeto.estado in (Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO)


def _puede_editar_formulario(user, objeto):
    if not _puede_editar(user, objeto) or _estado_terminal(objeto):
        return False
    return not isinstance(objeto, Hito) or obtener_rol(user) in ROLES_GESTORES


def _filtrar_propios(queryset, request):
    if obtener_rol(request.user) not in ROLES_GESTORES:
        return queryset.filter(Q(responsable=request.user) | Q(creado_por=request.user))
    return queryset


def _filtro_hitos(request):
    delegaciones = delegaciones_autorizadas(request.user)
    activa = get_delegacion_activa(request)
    if obtener_rol(request.user) == 'administrador' and activa is None:
        return Hito.objects.all()
    ids = delegaciones.filter(pk=activa.pk).values('pk') if activa else delegaciones.none().values('pk')
    return Hito.objects.filter(
        Q(actividad__delegacion__in=ids)
        | Q(gestion_social__delegacion__in=ids)
        | Q(compromiso__delegacion__in=ids)
    )


class ListaModulo(LoginRequiredMixin, ListView):
    paginate_by = 25
    ordering = '-creado_en'
    estado_parametro = 'estado'

    def filtrar_queryset(self, queryset):
        rol = obtener_rol(self.request.user)
        if rol not in ROLES_VALIDOS:
            raise PermissionDenied
        if self.model is Hito:
            queryset = _filtro_hitos(self.request)
        else:
            queryset = filtrar_contexto_territorial(queryset, self.request)
        queryset = _filtrar_propios(queryset, self.request)

        estado = self.request.GET.get('estado', '').strip()
        q = self.request.GET.get('q', '').strip()
        if estado:
            queryset = queryset.filter(estado=estado)
        if q:
            if self.model is GestionSocial:
                queryset = queryset.filter(
                    Q(codigo__icontains=q) | Q(titulo__icontains=q)
                    | Q(vecino__nombres__icontains=q) | Q(vecino__apellidos__icontains=q)
                )
            elif self.model is Carta:
                queryset = queryset.filter(
                    Q(codigo__icontains=q) | Q(asunto__icontains=q)
                    | Q(vecino__nombres__icontains=q) | Q(vecino__apellidos__icontains=q)
                )
            elif self.model is Hito:
                queryset = queryset.filter(Q(codigo__icontains=q) | Q(titulo__icontains=q))
        return queryset.order_by(self.ordering, 'pk')

    def get_queryset(self):
        return self.filtrar_queryset(self.model.objects.all())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            q=self.request.GET.get('q', ''),
            estado=self.request.GET.get('estado', ''),
            estados=self.model.Estado.choices,
            puede_crear=obtener_rol(self.request.user) in self.roles_creacion,
        )
        return context


class ListaGestionSocial(ListaModulo):
    model = GestionSocial
    template_name = 'operaciones/gestion_social/lista.html'
    context_object_name = 'registros'
    roles_creacion = ROLES_VALIDOS
    ordering = '-fecha_ingreso'

    def get_queryset(self):
        return self.filtrar_queryset(
            GestionSocial.objects.select_related('delegacion', 'territorio', 'responsable')
        ).filter(activo=True)


class ListaCartas(ListaModulo):
    model = Carta
    template_name = 'operaciones/cartas/lista.html'
    context_object_name = 'registros'
    roles_creacion = ROLES_VALIDOS
    ordering = '-fecha_ingreso'

    def get_queryset(self):
        return self.filtrar_queryset(
            Carta.objects.select_related('delegacion', 'territorio', 'responsable')
        ).filter(activo=True)


class ListaHitos(ListaModulo):
    model = Hito
    template_name = 'operaciones/hitos/lista.html'
    context_object_name = 'registros'
    roles_creacion = ('administrador', 'delegado')
    ordering = 'fecha_programada'

    def get_queryset(self):
        return self.filtrar_queryset(
            Hito.objects.select_related(
                'responsable', 'actividad__delegacion', 'gestion_social__delegacion',
                'compromiso__delegacion',
            )
        ).filter(activo=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['hoy'] = timezone.localdate()
        context['limite_proximo'] = timezone.localdate() + timedelta(days=7)
        return context


class CrearModulo(LoginRequiredMixin, CreateView):
    success_message = 'Registro creado correctamente.'
    success_url_name = ''
    roles_creacion = ROLES_VALIDOS

    def dispatch(self, request, *args, **kwargs):
        if obtener_rol(request.user) not in self.roles_creacion:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.creado_por = self.request.user
            if self.object.responsable_id is None:
                self.object.responsable = self.request.user
            self.object.save()
            registrar_auditoria(
                self.request, f'crear_{self.audit_modelo}', self.object,
                f'{self.audit_etiqueta} {self.object.codigo} creado.',
            )
        messages.success(self.request, self.success_message)
        return redirect(self.success_url_name)


class CrearGestionSocial(CrearModulo):
    model = GestionSocial
    form_class = GestionSocialForm
    template_name = 'operaciones/gestion_social/form.html'
    success_url_name = 'atenciones:gestion_social:lista'
    audit_modelo = 'gestion_social'
    audit_etiqueta = 'Gestión social'


class CrearCarta(CrearModulo):
    model = Carta
    form_class = CartaForm
    template_name = 'operaciones/cartas/form.html'
    success_url_name = 'agenda:cartas:lista'
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class CrearHito(CrearModulo):
    model = Hito
    form_class = HitoForm
    template_name = 'operaciones/hitos/form.html'
    success_url_name = 'agenda:hitos:lista'
    roles_creacion = ('administrador', 'delegado')
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'


class EditarModulo(LoginRequiredMixin, UpdateView):
    def get_queryset(self):
        if self.model is Hito:
            queryset = _filtro_hitos(self.request)
        else:
            queryset = filtrar_contexto_territorial(self.model.objects.all(), self.request)
        queryset = _filtrar_propios(queryset, self.request)
        if self.model is Hito:
            queryset = queryset.exclude(
                estado__in=(Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO),
            )
        else:
            queryset = queryset.exclude(
                estado__in=(
                    self.model.Estado.CERRADA,
                )
            )
        return queryset

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not _puede_editar(request.user, self.object):
            raise PermissionDenied
        return response

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        previo = self.object.responsable_id
        motivo = form.cleaned_data.get('motivo_cambio', '').strip()
        with transaction.atomic():
            objeto = form.save()
            nota = f'{self.audit_etiqueta} {objeto.codigo} actualizado.'
            if previo != objeto.responsable_id:
                nota += (
                    f' Responsable reasignado de usuario {previo} a {objeto.responsable_id}. '
                    f'Motivo: {motivo}'
                )
            registrar_auditoria(self.request, f'actualizar_{self.audit_modelo}', objeto, nota)
        messages.success(self.request, 'Cambios guardados correctamente.')
        return redirect(self.success_url_name, pk=objeto.pk)


class EditarGestionSocial(EditarModulo):
    model = GestionSocial
    form_class = GestionSocialForm
    template_name = 'operaciones/gestion_social/form.html'
    success_url_name = 'atenciones:gestion_social:detalle'
    audit_modelo = 'gestion_social'
    audit_etiqueta = 'Gestión social'


class EditarCarta(EditarModulo):
    model = Carta
    form_class = CartaForm
    template_name = 'operaciones/cartas/form.html'
    success_url_name = 'agenda:cartas:detalle'
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class EditarHito(EditarModulo):
    model = Hito
    form_class = HitoForm
    template_name = 'operaciones/hitos/form.html'
    success_url_name = 'agenda:hitos:detalle'
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
    roles_creacion = ROLES_GESTORES

    def dispatch(self, request, *args, **kwargs):
        if obtener_rol(request.user) not in self.roles_creacion:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class DetalleModulo(LoginRequiredMixin, View):
    model = None
    template_name = ''
    success_url_name = ''
    transiciones = {}

    def get_queryset(self):
        if self.model is Hito:
            queryset = _filtro_hitos(self.request)
        else:
            queryset = filtrar_contexto_territorial(self.model.objects.all(), self.request)
        return _filtrar_propios(queryset, self.request).select_related(
            'responsable', 'creado_por',
        )

    def get(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        objeto = get_object_or_404(self.get_queryset(), pk=pk)
        context = {
            'registro': objeto,
            'puede_editar': _puede_editar_formulario(request.user, objeto),
            'transiciones': self.transiciones.get(objeto.estado, ()),
            'form_estado': CambioEstadoForm(
                choices=self.transiciones.get(objeto.estado, ()),
            ),
            'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        objeto = get_object_or_404(self.get_queryset(), pk=pk)
        if not _puede_editar(request.user, objeto):
            raise PermissionDenied
        form = CambioEstadoForm(
            request.POST, choices=self.transiciones.get(objeto.estado, ()),
        )
        if not form.is_valid():
            return render(request, self.template_name, {
                'registro': objeto,
                'puede_editar': _puede_editar_formulario(request.user, objeto),
                'transiciones': self.transiciones.get(objeto.estado, ()),
                'form_estado': form,
                'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
            }, status=400)
        anterior = objeto.estado
        estado = form.cleaned_data['estado']
        objeto.estado = estado
        if isinstance(objeto, Carta) and estado == Carta.Estado.RESPONDIDA:
            objeto.respuesta = form.cleaned_data['respuesta'].strip()
            objeto.fecha_respuesta = timezone.localdate()
        elif isinstance(objeto, Carta) and estado == Carta.Estado.EN_PROCESO:
            objeto.fecha_respuesta = None
        if isinstance(objeto, Hito):
            if estado == Hito.Estado.COMPLETADO:
                objeto.fecha_completada = form.cleaned_data['fecha_completada']
                if not objeto.fecha_completada:
                    form.add_error('fecha_completada', 'Indique la fecha de término.')
            elif estado == Hito.Estado.CANCELADO:
                objeto.motivo_cambio = form.cleaned_data['motivo'].strip()
                if not objeto.motivo_cambio:
                    form.add_error('motivo', 'Indique el motivo de cancelación.')
            else:
                objeto.fecha_completada = None
        if form.errors:
            return render(request, self.template_name, {
                'registro': objeto,
                'puede_editar': True,
                'transiciones': self.transiciones.get(anterior, ()),
                'form_estado': form,
                'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
            }, status=400)
        with transaction.atomic():
            objeto.save()
            registrar_auditoria(
                request, f'cambiar_estado_{self.audit_modelo}', objeto,
                f'{self.audit_etiqueta} {objeto.codigo}: {anterior} → {estado}.',
            )
        messages.success(request, 'Estado actualizado correctamente.')
        return redirect(self.success_url_name, pk=objeto.pk)


class DetalleGestionSocial(DetalleModulo):
    model = GestionSocial
    template_name = 'operaciones/gestion_social/detalle.html'
    success_url_name = 'atenciones:gestion_social:detalle'
    audit_modelo = 'gestion_social'
    audit_etiqueta = 'Gestión social'
    transiciones = {
        GestionSocial.Estado.REGISTRADA: (
            (GestionSocial.Estado.EN_PROCESO, 'En proceso'),
            (GestionSocial.Estado.DERIVADA, 'Derivada'),
        ),
        GestionSocial.Estado.EN_PROCESO: (
            (GestionSocial.Estado.PENDIENTE_ANTECEDENTES, 'Pendiente de antecedentes'),
            (GestionSocial.Estado.DERIVADA, 'Derivada'),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
        GestionSocial.Estado.PENDIENTE_ANTECEDENTES: (
            (GestionSocial.Estado.EN_PROCESO, 'En proceso'),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
        GestionSocial.Estado.DERIVADA: (
            (GestionSocial.Estado.EN_PROCESO, 'En proceso'),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
    }


class DetalleCarta(DetalleModulo):
    model = Carta
    template_name = 'operaciones/cartas/detalle.html'
    success_url_name = 'agenda:cartas:detalle'
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'
    transiciones = {
        Carta.Estado.INGRESADA: (
            (Carta.Estado.ASIGNADA, 'Asignada'),
            (Carta.Estado.EN_PROCESO, 'En proceso'),
        ),
        Carta.Estado.ASIGNADA: ((Carta.Estado.EN_PROCESO, 'En proceso'),),
        Carta.Estado.EN_PROCESO: ((Carta.Estado.RESPONDIDA, 'Respondida'),),
        Carta.Estado.RESPONDIDA: (
            (Carta.Estado.CERRADA, 'Cerrada'),
            (Carta.Estado.EN_PROCESO, 'Reabrir en proceso'),
        ),
    }


class DetalleHito(DetalleModulo):
    model = Hito
    template_name = 'operaciones/hitos/detalle.html'
    success_url_name = 'agenda:hitos:detalle'
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
    transiciones = {
        Hito.Estado.PENDIENTE: (
            (Hito.Estado.EN_PROCESO, 'En proceso'),
            (Hito.Estado.CANCELADO, 'Cancelar'),
        ),
        Hito.Estado.EN_PROCESO: (
            (Hito.Estado.COMPLETADO, 'Completado'),
            (Hito.Estado.CANCELADO, 'Cancelar'),
        ),
    }


class DesactivarModulo(LoginRequiredMixin, View):
    model = None
    detail_url_name = ''
    audit_modelo = ''
    audit_etiqueta = ''

    def post(self, request, pk):
        if obtener_rol(request.user) not in ROLES_GESTORES:
            raise PermissionDenied
        if self.model is Hito:
            queryset = _filtro_hitos(request)
        else:
            queryset = filtrar_contexto_territorial(self.model.objects.all(), request)
        objeto = get_object_or_404(queryset, pk=pk)
        with transaction.atomic():
            objeto.activo = False
            objeto.save(update_fields=['activo', 'actualizado_en'])
            registrar_auditoria(
                request, f'desactivar_{self.audit_modelo}', objeto,
                f'{self.audit_etiqueta} {objeto.codigo} desactivado.',
            )
        messages.success(request, 'Registro desactivado correctamente.')
        return redirect(self.detail_url_name, pk=objeto.pk)


class DesactivarGestionSocial(DesactivarModulo):
    model = GestionSocial
    detail_url_name = 'atenciones:gestion_social:detalle'
    audit_modelo = 'gestion_social'
    audit_etiqueta = 'Gestión social'


class DesactivarCarta(DesactivarModulo):
    model = Carta
    detail_url_name = 'agenda:cartas:detalle'
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class DesactivarHito(DesactivarModulo):
    model = Hito
    detail_url_name = 'agenda:hitos:detalle'
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
