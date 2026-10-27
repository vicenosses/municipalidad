from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from sgr.forms import IndicadorFiltroForm, IndicadorForm
from sgr.calculos import calcular_avance_indicador, calcular_resultado_indicador
from sgr.models import Indicador
from sgr.ponderaciones import ponderar_resultado
from sgr.permisos import (
    ROLES_ESTADO_META, ROLES_METAS, indicador_modificable, indicadores_visibles,
    metas_visibles, puede_crear_meta,
)
from usuarios.mixins import RolRequiredMixin, obtener_rol


class IndicadorConsultaMixin(RolRequiredMixin):
    roles_permitidos = ROLES_METAS
    model = Indicador

    def get_queryset(self):
        return indicadores_visibles(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['puede_crear_indicador'] = puede_crear_meta(self.request)
        context['puede_estado_indicador'] = obtener_rol(self.request.user) in ROLES_ESTADO_META
        return context


class IndicadorListView(IndicadorConsultaMixin, ListView):
    template_name = 'sgr/indicadores/lista.html'
    context_object_name = 'indicadores'
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset()
        self.filtro = IndicadorFiltroForm(self.request.GET or None, request=self.request)
        if not self.filtro.is_bound:
            return qs
        if not self.filtro.is_valid():
            return qs.none()
        datos = self.filtro.cleaned_data
        if datos['periodo']:
            qs = qs.filter(meta__periodo=datos['periodo'])
        if datos['meta']:
            qs = qs.filter(meta=datos['meta'])
        if datos['estado']:
            qs = qs.filter(activo=datos['estado'] == 'activo')
        if datos['unidad']:
            qs = qs.filter(unidad_medida=datos['unidad'])
        if datos.get('delegacion'):
            qs = qs.filter(meta__delegacion=datos['delegacion'])
        if datos['buscar']:
            qs = qs.filter(Q(nombre__icontains=datos['buscar']) | Q(descripcion__icontains=datos['buscar']))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.filtro
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context['query_params'] = parametros.urlencode()
        return context


class IndicadorDetailView(IndicadorConsultaMixin, DetailView):
    template_name = 'sgr/indicadores/detalle.html'
    context_object_name = 'indicador'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['historial_objetivo'] = self.object.historial_objetivo.select_related('usuario')
        context['avance_actividades'] = calcular_avance_indicador(self.object)
        context['resultado_indicador'] = calcular_resultado_indicador(self.object)
        context['ponderacion_indicador'] = ponderar_resultado(self.object, context['resultado_indicador'])
        context['historial_ponderacion'] = self.object.historial_ponderacion.select_related('usuario')
        return context


class IndicadorGuardarMixin(IndicadorConsultaMixin):
    form_class = IndicadorForm
    template_name = 'sgr/indicadores/formulario.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        kwargs['meta_origen'] = self.get_meta_origen()
        return kwargs

    def get_meta_origen(self):
        if 'meta_pk' not in self.kwargs:
            return None
        meta = get_object_or_404(metas_visibles(self.request), pk=self.kwargs['meta_pk'])
        if not (meta.activo and meta.periodo.activo):
            raise PermissionDenied('Reactive la Meta y su Período antes de crear Indicadores.')
        return meta

    def form_valid(self, form):
        nuevo = form.instance.pk is None
        if nuevo:
            form.instance.creado_por = self.request.user
        try:
            with transaction.atomic():
                respuesta = super().form_valid(form)
                registrar_auditoria(
                    self.request, 'crear_indicador' if nuevo else 'editar_indicador', self.object,
                    f'Se {"creó" if nuevo else "editó"} el indicador "{self.object.nombre}" '
                    f'para la meta "{self.object.meta}". Objetivo: {self.object.objetivo_display}; '
                    f'{self.object.get_sentido_display()}. Ponderación: {self.object.ponderacion_display}.',
                )
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Indicador guardado correctamente.')
        return respuesta


class IndicadorCreateView(IndicadorGuardarMixin, CreateView):
    def test_func(self):
        return super().test_func() and puede_crear_meta(self.request)


class IndicadorUpdateView(IndicadorGuardarMixin, UpdateView):
    def get_object(self, queryset=None):
        indicador = super().get_object(queryset)
        if not indicador_modificable(indicador):
            raise PermissionDenied('Reactive la Meta y su Período antes de editar el Indicador.')
        return indicador


class IndicadorEstadoView(IndicadorConsultaMixin, View):
    roles_permitidos = ROLES_ESTADO_META
    http_method_names = ['post']

    def post(self, request, pk):
        with transaction.atomic():
            indicador = get_object_or_404(self.get_queryset(), pk=pk)
            if not indicador_modificable(indicador):
                raise PermissionDenied('Reactive la Meta y su Período antes de cambiar el estado del Indicador.')
            valor = request.POST.get('activo')
            if valor not in ('true', 'false'):
                messages.error(request, 'Seleccione un estado válido.')
                return redirect(indicador)
            activo = valor == 'true'
            if indicador.activo == activo:
                return redirect(indicador)
            indicador.activo = activo
            try:
                indicador.save()
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return redirect(indicador)
            registrar_auditoria(
                request, 'activar_indicador' if activo else 'desactivar_indicador', indicador,
                f'Se {"activó" if activo else "desactivó"} el indicador "{indicador.nombre}" '
                f'para la meta "{indicador.meta}".',
            )
        messages.success(request, 'Estado del Indicador actualizado.')
        return redirect(indicador)
