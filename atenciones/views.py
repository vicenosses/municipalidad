from django.contrib import messages
from django.db import transaction
from django.core.exceptions import ValidationError
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView

from atenciones.forms import (
    AtencionCiudadanaForm,
    AtencionVaAlTuboForm,
    FiltroVaAlTuboForm,
)
from atenciones.models import AtencionCiudadana
from atenciones.estados import cambiar_estado_actividad, registrar_creacion_actividad
from atenciones.permisos import (
    ROLES_GESTORES_ESTADO, ROLES_OPERATIVOS_ESTADO, puede_cambiar_estado, queryset_atenciones,
)
from agenda.views import puede_crear_compromiso_desde_actividad
from auditoria.utils import registrar_auditoria
from auditoria.historial import historial_actividad
from sgr.aportes import pendientes_validacion, puede_proponer, proponer_aporte
from sgr.models import AporteIndicador
from sgr.plazos import limite_asociacion
from config.listado import FiltroExportMixin
from evidencias.permisos import puede_agregar_evidencia
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import (
    get_delegacion_activa,
    en_contexto_delegacion,
    usuario_tiene_alcance_delegacion,
)

def puede_cambiar_disponibilidad(request, atencion):
    rol = obtener_rol(request.user)
    if rol == 'administrador':
        return en_contexto_delegacion(request, atencion.delegacion)
    return (
        rol == 'delegado'
        and usuario_tiene_alcance_delegacion(request.user, atencion.delegacion)
        and get_delegacion_activa(request) == atencion.delegacion
    )


def puede_cambiar_va_al_tubo(request, atencion):
    if (
        not atencion.activo
        or atencion.estado == AtencionCiudadana.Estado.CERRADA
    ):
        return False

    rol = obtener_rol(request.user)
    if rol == 'administrador':
        return en_contexto_delegacion(request, atencion.delegacion)
    if rol not in (
        'delegado',
        'coordinador',
        'funcionario',
        'verificador',
    ):
        return False

    delegacion = get_delegacion_activa(request)
    if (
        delegacion != atencion.delegacion
        or not usuario_tiene_alcance_delegacion(request.user, atencion.delegacion)
    ):
        return False
    if rol in ('funcionario', 'verificador'):
        return atencion.creado_por_id == request.user.pk
    return True


def estados_disponibles(request, atencion):
    return [
        (estado, etiqueta)
        for estado, etiqueta in AtencionCiudadana.Estado.choices
        if puede_cambiar_estado(request, atencion, estado)
    ]


class AtencionListView(FiltroExportMixin, LoginRequiredMixin, ListView):
    model = AtencionCiudadana
    template_name = 'atenciones/lista.html'
    context_object_name = 'atenciones'
    search_fields = (
        'titulo',
        'solicitante',
        'descripcion',
        'tipo__nombre',
        'subatencion__nombre',
        'delegacion__nombre',
        'responsable__username',
    )
    export_filename = 'atenciones.xlsx'
    export_headers = (
        'Fecha de actividad',
        'Título',
        'Responsable',
        'Creado por',
        'Delegación',
        'Estado',
        'Va al tubo',
    )
    export_fields = (
        'fecha',
        'titulo',
        'responsable.get_full_name',
        'creador_historico_display',
        'delegacion.nombre',
        'get_estado_display',
        'va_al_tubo',
    )

    def get_queryset(self):
        queryset = self.filtrar_queryset(
            queryset_atenciones(self.request).prefetch_related('evidencias')
        )
        self.filtro_va_al_tubo = FiltroVaAlTuboForm(self.request.GET)
        if self.filtro_va_al_tubo.is_valid():
            valor = self.filtro_va_al_tubo.cleaned_data['va_al_tubo']
            if valor in ('true', 'false'):
                queryset = queryset.filter(va_al_tubo=(valor == 'true'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for atencion in context['atenciones']:
            atencion.estados_disponibles = estados_disponibles(
                self.request,
                atencion,
            )
        context['atenciones_con_permiso_disponibilidad'] = {
            atencion.pk
            for atencion in context['atenciones']
            if puede_cambiar_disponibilidad(self.request, atencion)
        }
        context['atenciones_con_permiso_va_al_tubo'] = {
            atencion.pk
            for atencion in context['atenciones']
            if puede_cambiar_va_al_tubo(self.request, atencion)
        }
        context['filtro_va_al_tubo'] = getattr(
            self,
            'filtro_va_al_tubo',
            FiltroVaAlTuboForm(self.request.GET),
        )
        context['atenciones_con_permiso_evidencia'] = {
            atencion.pk
            for atencion in context['atenciones']
            if puede_agregar_evidencia(self.request, atencion)
        }
        return context


class AtencionDetailView(LoginRequiredMixin, DetailView):
    model = AtencionCiudadana
    template_name = 'atenciones/detalle.html'
    context_object_name = 'atencion'

    def get_queryset(self):
        return queryset_atenciones(self.request).prefetch_related(
            'evidencias',
            'compromisos__responsable',
            'compromisos__delegacion',
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        atencion = self.object
        aporte = AporteIndicador.objects.select_related('indicador__meta__periodo', 'validado_por').filter(actividad=atencion).first()
        context['aporte_sgr'] = aporte
        context['puede_proponer_aporte'] = puede_proponer(self.request, atencion, aporte)
        context['puede_validar_aporte'] = aporte is not None and pendientes_validacion(self.request).filter(pk=aporte.pk).exists()
        context['limite_aporte'] = limite_asociacion(atencion.fecha)
        context['historial_aporte'] = aporte.historial.select_related(
            'usuario', 'indicador_anterior', 'indicador_nuevo') if aporte else []
        context['historial'] = historial_actividad(atencion)
        context['historial_estados'] = list(atencion.historial_estados.select_related('actor'))
        context['historial_estados_incompleto'] = not any(
            evento.estado_anterior == '' for evento in context['historial_estados']
        )
        context['estados_disponibles'] = estados_disponibles(
            self.request,
            atencion,
        )
        context['puede_cambiar_disponibilidad'] = puede_cambiar_disponibilidad(
            self.request,
            atencion,
        )
        context['puede_cambiar_va_al_tubo'] = puede_cambiar_va_al_tubo(
            self.request,
            atencion,
        )
        context['form_va_al_tubo'] = AtencionVaAlTuboForm(
            initial={'va_al_tubo': 'true' if atencion.va_al_tubo else 'false'}
        )
        compromisos = atencion.compromisos.select_related(
            'responsable',
            'delegacion',
        ).order_by('fecha_hora')
        if get_delegacion_activa(self.request) is not None or obtener_rol(self.request.user) != 'administrador':
            compromisos = compromisos.filter(delegacion=atencion.delegacion)
        context['compromisos_relacionados'] = compromisos
        context['puede_agregar_a_agenda'] = puede_crear_compromiso_desde_actividad(
            self.request,
            atencion,
        )
        if (
            obtener_rol(self.request.user) == 'administrador'
            or atencion.responsable_id == self.request.user.pk
        ):
            context['evidencias'] = atencion.evidencias.select_related(
                'subido_por', 'validado_por'
            ).all()
        else:
            context['evidencias'] = atencion.evidencias.filter(
                estado='aprobada'
            ).select_related('subido_por', 'validado_por')
        return context


class AtencionEstadoView(RolRequiredMixin, View):
    roles_permitidos = (
        'administrador',
        'delegado',
        'coordinador',
        'funcionario',
        'verificador',
    )

    def post(self, request, pk):
        atencion = cambiar_estado_actividad(request, pk, request.POST.get('estado'), request.POST.get('motivo', ''))
        messages.success(request, f'Estado actualizado a {atencion.get_estado_display()}.')
        return redirect('atenciones:detalle', pk=atencion.pk)


class AtencionDisponibilidadView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'delegado')

    def post(self, request, pk):
        atencion = get_object_or_404(queryset_atenciones(request), pk=pk)
        if not puede_cambiar_disponibilidad(request, atencion):
            raise Http404

        valor_solicitado = request.POST.get('activo')
        if valor_solicitado not in ('true', 'false'):
            raise Http404
        activo = valor_solicitado == 'true'
        if atencion.activo == activo:
            raise Http404

        atencion.activo = activo
        atencion.save(update_fields=['activo'])
        accion = 'habilitar' if activo else 'deshabilitar'
        registrar_auditoria(
            request,
            accion,
            atencion,
            f'Actividad {accion}: {atencion.titulo}',
        )
        etiqueta = 'habilitada' if activo else 'deshabilitada'
        messages.success(request, f'Actividad {etiqueta}.')
        return redirect('atenciones:detalle', pk=atencion.pk)


class AtencionVaAlTuboView(RolRequiredMixin, View):
    roles_permitidos = (
        'administrador',
        'delegado',
        'coordinador',
        'funcionario',
        'verificador',
    )

    def post(self, request, pk):
        atencion = get_object_or_404(queryset_atenciones(request), pk=pk)
        if not puede_cambiar_va_al_tubo(request, atencion):
            raise Http404

        form = AtencionVaAlTuboForm(request.POST)
        if not form.is_valid():
            raise Http404

        valor_anterior = atencion.va_al_tubo
        valor_nuevo = form.cleaned_data['va_al_tubo'] == 'true'
        if valor_anterior != valor_nuevo:
            atencion.va_al_tubo = valor_nuevo
            atencion.save(update_fields=['va_al_tubo'])
            registrar_auditoria(
                request,
                'cambiar_va_al_tubo',
                atencion,
                (
                    f'Va al tubo: {"Sí" if valor_anterior else "No"} → '
                    f'{"Sí" if valor_nuevo else "No"}'
                ),
            )
            messages.success(request, 'Clasificación “Va al tubo” actualizada.')
        return redirect('atenciones:detalle', pk=atencion.pk)


class AtencionCreateView(RolRequiredMixin, CreateView):
    form_class = AtencionCiudadanaForm
    template_name = 'atenciones/form.html'
    success_url = reverse_lazy('atenciones:lista')
    roles_permitidos = ('administrador', 'coordinador', 'funcionario', 'delegado', 'verificador')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['delegacion_activa'] = get_delegacion_activa(self.request)
        context['subatenciones'] = context['form'].fields['subatencion'].queryset
        return context

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        delegacion = get_delegacion_activa(self.request)
        if delegacion is None:
            form.add_error(None, 'Debe tener una delegación activa para registrar la atención.')
            return self.form_invalid(form)
        form.instance.delegacion = delegacion
        form.instance.responsable = self.request.user
        form.instance.creado_por = self.request.user
        form.instance.estado = AtencionCiudadana.Estado.REGISTRADA
        try:
            with transaction.atomic():
                response = super().form_valid(form)
                registrar_creacion_actividad(form.instance, self.request.user)
                registrar_auditoria(self.request, 'crear', form.instance,
                                    f'Atención ciudadana de {form.instance.solicitante}')
                if form.cleaned_data.get('indicador'):
                    proponer_aporte(self.request, form.instance, form.cleaned_data['indicador'],
                                    form.cleaned_data.get('valor_declarado'))
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Atención ciudadana registrada.')
        return response
