from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views import View

from agenda.forms import CompromisoFiltroForm, CompromisoForm, SolicitudAmpliacionForm
from agenda.models import Compromiso, HistorialCompromiso, SolicitudAmpliacion
from atenciones.models import AtencionCiudadana
from auditoria.utils import registrar_auditoria
from evidencias.permisos import puede_agregar_evidencia
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import (
    delegaciones_autorizadas,
    get_delegacion_activa,
    en_contexto_delegacion,
    filtrar_contexto_territorial,
    usuario_tiene_alcance_delegacion,
)

User = get_user_model()
ROLES_AGENDA = ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario')
ROLES_GESTORES = ('administrador', 'delegado', 'coordinador')


def compromisos_visibles(request):
    qs = Compromiso.objects.select_related(
        'responsable', 'delegacion'
    ).prefetch_related('actividades', 'historial__realizado_por')
    return filtrar_contexto_territorial(qs, request)


def puede_gestionar(user, compromiso):
    rol = obtener_rol(user)
    if rol == 'administrador':
        return True
    return (
        rol in ('delegado', 'coordinador')
        and usuario_tiene_alcance_delegacion(user, compromiso.delegacion)
    )


def puede_editar_compromiso(user, compromiso):
    return puede_gestionar(user, compromiso) or (
        obtener_rol(user) in ('funcionario', 'verificador')
        and compromiso.responsable_id == user.pk
    )


def puede_crear_compromiso_desde_actividad(request, actividad):
    if (
        obtener_rol(request.user) not in ROLES_AGENDA
        or not actividad.activo
        or actividad.estado == AtencionCiudadana.Estado.CERRADA
    ):
        return False
    if obtener_rol(request.user) == 'administrador':
        return en_contexto_delegacion(request, actividad.delegacion)
    delegacion = get_delegacion_activa(request)
    return (
        delegacion == actividad.delegacion
        and usuario_tiene_alcance_delegacion(request.user, actividad.delegacion)
    )


def actividad_para_nuevo_compromiso(request, pk):
    queryset = filtrar_contexto_territorial(
        AtencionCiudadana.objects.select_related('delegacion'), request)
    actividad = get_object_or_404(queryset, pk=pk)
    if not puede_crear_compromiso_desde_actividad(request, actividad):
        raise Http404
    return actividad


class CompromisoListView(LoginRequiredMixin, ListView):
    model = Compromiso
    template_name = 'agenda/lista.html'
    context_object_name = 'compromisos'
    paginate_by = 25

    def get_queryset(self):
        qs = compromisos_visibles(self.request)
        self.filtro = CompromisoFiltroForm(
            self.request.GET or None,
            responsables=User.objects.filter(
                pk__in=qs.values_list('responsable_id', flat=True).distinct()
            ).order_by('username'),
        )
        if self.filtro.is_valid():
            datos = self.filtro.cleaned_data
            if datos.get('q'):
                qs = qs.filter(
                    Q(titulo__icontains=datos['q'])
                    | Q(solicitante__icontains=datos['q'])
                )
            if datos.get('estado'):
                qs = qs.filter(estado=datos['estado'])
            if datos.get('responsable'):
                qs = qs.filter(responsable=datos['responsable'])
            if datos.get('desde'):
                qs = qs.filter(fecha_hora__date__gte=datos['desde'])
            if datos.get('hasta'):
                qs = qs.filter(fecha_hora__date__lte=datos['hasta'])
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ahora = timezone.now()
        visibles = compromisos_visibles(self.request)
        context['filtro'] = getattr(self, 'filtro', CompromisoFiltroForm())
        context['vencidos'] = visibles.exclude(
            estado=Compromiso.Estado.REALIZADO
        ).filter(fecha_hora__lt=ahora)[:10]
        context['proximos'] = visibles.exclude(
            estado=Compromiso.Estado.REALIZADO
        ).filter(fecha_hora__gte=ahora, fecha_hora__lte=ahora + timedelta(days=7))[:10]
        context['puede_crear'] = obtener_rol(self.request.user) in ROLES_AGENDA
        context['puede_revisar_ampliaciones'] = obtener_rol(self.request.user) in ('administrador', 'delegado', 'coordinador', 'verificador')
        if context['puede_revisar_ampliaciones']:
            context['ampliaciones_pendientes'] = SolicitudAmpliacion.objects.filter(compromiso__in=visibles, estado='pendiente').count()
        return context


class CompromisoCreateView(RolRequiredMixin, CreateView):
    form_class = CompromisoForm
    template_name = 'agenda/form.html'
    success_url = reverse_lazy('agenda:lista')
    roles_permitidos = ROLES_AGENDA

    def get_actividad_origen(self):
        return None

    def get_delegacion_compromiso(self):
        return get_delegacion_activa(self.request)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        actividad_origen = self.get_actividad_origen()
        delegacion = self.get_delegacion_compromiso()
        delegaciones = [delegacion] if delegacion else []
        kwargs.update(
            user=self.request.user,
            delegacion=delegacion,
            delegaciones=delegaciones,
            es_creacion=True,
            actividad_origen=actividad_origen,
        )
        if actividad_origen is not None:
            kwargs['initial'] = {
                **kwargs.get('initial', {}),
                'actividades': [actividad_origen.pk],
            }
        return kwargs

    def form_valid(self, form):
        delegacion = self.get_delegacion_compromiso()
        if delegacion is None:
            form.add_error(None, 'Seleccione una delegación activa autorizada antes de crear un compromiso.')
            return self.form_invalid(form)
        form.instance.delegacion = delegacion
        form.instance.creado_por = self.request.user
        form.instance.estado = Compromiso.Estado.INGRESADO
        with transaction.atomic():
            response = super().form_valid(form)
            self.object.actividades.filter(va_al_tubo=False).update(va_al_tubo=True)
            HistorialCompromiso.objects.create(
                compromiso=self.object,
                campo='creacion',
                valor_nuevo=self.object.get_estado_display(),
                realizado_por=self.request.user,
            )
            registrar_auditoria(
                self.request,
                self.get_audit_action(),
                self.object,
                self.get_audit_description(),
            )
        messages.success(self.request, self.get_success_message())
        return response

    def get_audit_action(self):
        return 'crear'

    def get_audit_description(self):
        return f'Alta de compromiso: {self.object.titulo}'

    def get_success_message(self):
        return 'Compromiso ingresado a la agenda.'


class CompromisoDetailView(LoginRequiredMixin, DetailView):
    model = Compromiso
    template_name = 'agenda/detalle.html'
    context_object_name = 'compromiso'

    def get_queryset(self):
        return compromisos_visibles(self.request).prefetch_related(
            'evidencias__subido_por', 'evidencias__validado_por'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compromiso = self.object
        context['puede_editar'] = puede_editar_compromiso(self.request.user, compromiso)
        context['puede_subir_evidencia'] = puede_agregar_evidencia(
            self.request,
            compromiso,
        )
        actividades = compromiso.actividades.select_related(
            'delegacion'
        ).order_by('-fecha', 'titulo')
        if get_delegacion_activa(self.request) is not None or obtener_rol(self.request.user) != 'administrador':
            actividades = actividades.filter(delegacion=compromiso.delegacion)
        context['actividades_relacionadas'] = actividades
        context['puede_solicitar_ampliacion'] = (compromiso.responsable_id == self.request.user.pk and compromiso.estado != Compromiso.Estado.REALIZADO)
        context['form_ampliacion'] = SolicitudAmpliacionForm(compromiso=compromiso)
        context['solicitudes_ampliacion'] = compromiso.solicitudes_ampliacion.select_related('solicitante', 'decidido_por')
        return context


class SolicitarAmpliacionView(LoginRequiredMixin, View):
    def post(self, request, pk):
        with transaction.atomic():
            compromiso = get_object_or_404(compromisos_visibles(request).select_for_update(), pk=pk)
            if compromiso.responsable_id != request.user.pk or compromiso.estado == Compromiso.Estado.REALIZADO:
                raise PermissionDenied
            form = SolicitudAmpliacionForm(request.POST, compromiso=compromiso)
            if not form.is_valid():
                return render(request, 'agenda/solicitar_ampliacion.html', {'form': form, 'compromiso': compromiso}, status=400)
            if compromiso.solicitudes_ampliacion.filter(estado='pendiente').exists():
                messages.error(request, 'Ya existe una solicitud pendiente para este compromiso.')
                return redirect('agenda:detalle', pk=pk)
            solicitud = form.save(commit=False)
            solicitud.compromiso = compromiso
            solicitud.solicitante = request.user
            solicitud.plazo_anterior = compromiso.fecha_hora
            solicitud.save()
            registrar_auditoria(request, 'solicitar_ampliacion', compromiso, 'Solicitud de ampliación de plazo')
        messages.success(request, 'Solicitud de ampliación enviada para revisión.')
        return redirect('agenda:detalle', pk=pk)


class AmpliacionesListView(RolRequiredMixin, ListView):
    roles_permitidos = ('administrador', 'delegado', 'coordinador', 'verificador')
    template_name = 'agenda/ampliaciones.html'
    context_object_name = 'solicitudes'

    def get_queryset(self):
        return SolicitudAmpliacion.objects.filter(compromiso__in=compromisos_visibles(self.request), estado='pendiente').select_related('compromiso', 'solicitante')


class DecidirAmpliacionView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado', 'coordinador', 'verificador')

    def post(self, request, pk):
        accion = request.POST.get('accion')
        if accion not in ('aprobar', 'rechazar'):
            raise PermissionDenied
        with transaction.atomic():
            solicitud = get_object_or_404(SolicitudAmpliacion.objects.select_for_update().select_related('compromiso'), pk=pk, compromiso__in=compromisos_visibles(request))
            compromiso = Compromiso.objects.select_for_update().get(pk=solicitud.compromiso_id)
            if solicitud.estado != 'pendiente':
                messages.error(request, 'Esta solicitud ya fue resuelta.')
            elif accion == 'aprobar' and (compromiso.estado == Compromiso.Estado.REALIZADO or compromiso.fecha_hora != solicitud.plazo_anterior):
                messages.error(request, 'El compromiso cambió; rechace la solicitud o revise el plazo actual.')
            else:
                if accion == 'aprobar':
                    compromiso.fecha_hora = solicitud.plazo_propuesto
                    compromiso.save(update_fields=['fecha_hora'])
                    HistorialCompromiso.objects.create(compromiso=compromiso, campo='fecha_hora', valor_anterior=solicitud.plazo_anterior.isoformat(), valor_nuevo=solicitud.plazo_propuesto.isoformat(), motivo=solicitud.motivo, realizado_por=request.user)
                solicitud.estado = 'aprobada' if accion == 'aprobar' else 'rechazada'
                solicitud.decidido_por = request.user
                solicitud.fecha_decision = timezone.now()
                solicitud.save(update_fields=['estado', 'decidido_por', 'fecha_decision'])
                registrar_auditoria(request, solicitud.estado, compromiso, 'Decisión de solicitud de ampliación de plazo')
                messages.success(request, 'Solicitud resuelta correctamente.')
        return redirect('agenda:ampliaciones')


class CompromisoDesdeActividadView(CompromisoCreateView):
    def get_actividad_origen(self):
        if not hasattr(self, '_actividad_origen'):
            self._actividad_origen = actividad_para_nuevo_compromiso(
                self.request,
                self.kwargs['actividad_pk'],
            )
        return self._actividad_origen

    def get_delegacion_compromiso(self):
        return self.get_actividad_origen().delegacion

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['actividad_origen'] = self.get_actividad_origen()
        return context

    def get_success_url(self):
        return reverse('agenda:detalle', kwargs={'pk': self.object.pk})

    def get_audit_action(self):
        return 'crear_compromiso_desde_actividad'

    def get_audit_description(self):
        actividad = self.get_actividad_origen()
        return (
            f'Compromiso {self.object.titulo} creado desde la actividad '
            f'{actividad.pk}: {actividad.titulo}'
        )

    def get_success_message(self):
        return 'Compromiso creado y asociado correctamente a la actividad.'


class CompromisoUpdateView(LoginRequiredMixin, UpdateView):
    model = Compromiso
    form_class = CompromisoForm
    template_name = 'agenda/form.html'
    context_object_name = 'compromiso'

    def get_queryset(self):
        return compromisos_visibles(self.request)

    def get_object(self, queryset=None):
        compromiso = super().get_object(queryset)
        if not puede_editar_compromiso(self.request.user, compromiso):
            raise PermissionDenied
        return compromiso

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(
            user=self.request.user,
            delegaciones=[self.object.delegacion],
        )
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['es_edicion'] = True
        return context

    def form_valid(self, form):
        compromiso = self.get_object()
        previo = {
            'estado': compromiso.get_estado_display(),
            'responsable': str(compromiso.responsable),
            'fecha_hora': compromiso.fecha_hora.isoformat(),
            'titulo': compromiso.titulo,
            'descripcion': compromiso.descripcion,
            'solicitante': compromiso.solicitante,
            'area_apoyo': compromiso.area_apoyo,
            'observaciones': compromiso.observaciones,
            'actividades': set(compromiso.actividades.values_list('pk', flat=True)),
        }
        motivo = form.cleaned_data.get('motivo_cambio', '')
        with transaction.atomic():
            response = super().form_valid(form)
            compromiso.refresh_from_db()
            compromiso.actividades.filter(va_al_tubo=False).update(va_al_tubo=True)
            nuevos = {
                'estado': compromiso.get_estado_display(),
                'responsable': str(compromiso.responsable),
                'fecha_hora': compromiso.fecha_hora.isoformat(),
                'titulo': compromiso.titulo,
                'descripcion': compromiso.descripcion,
                'solicitante': compromiso.solicitante,
                'area_apoyo': compromiso.area_apoyo,
                'observaciones': compromiso.observaciones,
                'actividades': set(compromiso.actividades.values_list('pk', flat=True)),
            }
            for campo, anterior in previo.items():
                nuevo = nuevos[campo]
                if anterior != nuevo:
                    HistorialCompromiso.objects.create(
                        compromiso=compromiso,
                        campo=campo,
                        valor_anterior=', '.join(map(str, anterior)) if isinstance(anterior, set) else anterior,
                        valor_nuevo=', '.join(map(str, nuevo)) if isinstance(nuevo, set) else nuevo,
                        motivo=motivo if campo == 'responsable' else '',
                        realizado_por=self.request.user,
                    )
            if compromiso.estado == Compromiso.Estado.REALIZADO and not compromiso.fecha_realizacion:
                compromiso.fecha_realizacion = timezone.now()
                compromiso.save(update_fields=['fecha_realizacion'])
            registrar_auditoria(
                self.request,
                'editar',
                compromiso,
                f'Actualización del compromiso: {compromiso.titulo}',
            )
        messages.success(self.request, 'Compromiso actualizado; sus cambios quedaron registrados.')
        return response

    def get_success_url(self):
        return reverse('agenda:detalle', kwargs={'pk': self.object.pk})
