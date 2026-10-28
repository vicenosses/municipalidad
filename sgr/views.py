from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from sgr.forms import MetaFiltroForm, MetaForm, PeriodoFiltroForm, PeriodoForm
from sgr.models import Meta, Periodo
from sgr.ponderaciones import calcular_resultado_meta
from sgr.permisos import ROLES_ESTADO_META, ROLES_METAS, indicadores_visibles, metas_visibles, puede_crear_meta
from usuarios.mixins import RolRequiredMixin, obtener_rol


class PeriodoConsultaMixin(RolRequiredMixin):
    roles_permitidos = ('administrador', 'delegado', 'coordinador')
    model = Periodo

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['puede_administrar'] = obtener_rol(self.request.user) == 'administrador'
        return context


class PeriodoListView(PeriodoConsultaMixin, ListView):
    template_name = 'sgr/periodos/lista.html'
    context_object_name = 'periodos'
    paginate_by = 50

    def get_queryset(self):
        qs = Periodo.objects.select_related('creado_por').order_by('-activo', '-fecha_inicio', '-pk')
        self.filtro = PeriodoFiltroForm(self.request.GET or None)
        if not self.filtro.is_bound:
            return qs
        if not self.filtro.is_valid():
            return qs.none()
        datos = self.filtro.cleaned_data
        if datos['estado']:
            qs = qs.filter(activo=datos['estado'] == 'activo')
        if datos['anio']:
            anio = datos['anio']
            qs = qs.filter(fecha_inicio__lte=date(anio, 12, 31),
                           fecha_fin__gte=date(anio, 1, 1))
        if datos['buscar']:
            qs = qs.filter(nombre__icontains=datos['buscar'])
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = self.filtro
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context['query_params'] = parametros.urlencode()
        return context


class PeriodoDetailView(PeriodoConsultaMixin, DetailView):
    template_name = 'sgr/periodos/detalle.html'
    context_object_name = 'periodo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['metas'] = metas_visibles(self.request).filter(periodo=self.object).order_by('-activo', 'nombre', 'pk')
        context['puede_crear_meta'] = self.object.activo and puede_crear_meta(self.request)
        context['puede_estado_meta'] = obtener_rol(self.request.user) in ROLES_ESTADO_META
        return context


class PeriodoGuardarMixin(RolRequiredMixin):
    roles_permitidos = ('administrador',)
    model = Periodo
    form_class = PeriodoForm
    template_name = 'sgr/periodos/formulario.html'

    def form_valid(self, form):
        nuevo = form.instance.pk is None
        if nuevo:
            form.instance.creado_por = self.request.user
        try:
            with transaction.atomic():
                respuesta = super().form_valid(form)
                registrar_auditoria(
                    self.request, 'crear_periodo' if nuevo else 'editar_periodo', self.object,
                    f'Se {"creó" if nuevo else "editó"} el período "{self.object.nombre}" '
                    f'({self.object.fecha_inicio:%d/%m/%Y} - {self.object.fecha_fin:%d/%m/%Y}).',
                )
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Período guardado correctamente.')
        return respuesta


class PeriodoCreateView(PeriodoGuardarMixin, CreateView):
    pass


class PeriodoUpdateView(PeriodoGuardarMixin, UpdateView):
    pass


class PeriodoEstadoView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)
    http_method_names = ['post']

    def post(self, request, pk):
        with transaction.atomic():
            periodo = get_object_or_404(Periodo.objects.select_for_update(), pk=pk)
            valor = request.POST.get('activo')
            if valor not in ('true', 'false'):
                messages.error(request, 'Seleccione un estado válido.')
                return redirect(periodo)
            activo = valor == 'true'
            if periodo.activo == activo:
                return redirect(periodo)
            periodo.activo = activo
            try:
                periodo.save()
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return redirect(periodo)
            registrar_auditoria(
                request, 'activar_periodo' if activo else 'desactivar_periodo', periodo,
                f'Se {"activó" if activo else "desactivó"} el período "{periodo.nombre}" '
                f'({periodo.fecha_inicio:%d/%m/%Y} - {periodo.fecha_fin:%d/%m/%Y}).',
            )
        messages.success(request, 'Estado del período actualizado.')
        return redirect(periodo)


class MetaConsultaMixin(RolRequiredMixin):
    roles_permitidos = ROLES_METAS
    model = Meta

    def get_queryset(self):
        return metas_visibles(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['puede_crear_meta'] = puede_crear_meta(self.request)
        context['puede_estado_meta'] = obtener_rol(self.request.user) in ROLES_ESTADO_META
        return context


class MetaListView(MetaConsultaMixin, ListView):
    template_name = 'sgr/metas/lista.html'
    context_object_name = 'metas'
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset().order_by('-activo', '-periodo__fecha_inicio', 'nombre', 'pk')
        self.filtro = MetaFiltroForm(self.request.GET or None, request=self.request)
        if not self.filtro.is_bound:
            return qs
        if not self.filtro.is_valid():
            return qs.none()
        datos = self.filtro.cleaned_data
        if datos['periodo']:
            qs = qs.filter(periodo=datos['periodo'])
        if datos['estado']:
            qs = qs.filter(activo=datos['estado'] == 'activa')
        if datos.get('delegacion'):
            qs = qs.filter(delegacion=datos['delegacion'])
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


class MetaDetailView(MetaConsultaMixin, DetailView):
    template_name = 'sgr/metas/detalle.html'
    context_object_name = 'meta'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['resultado_meta'] = calcular_resultado_meta(self.object)
        context['indicadores'] = sorted((fila.indicador for fila in context['resultado_meta'].indicadores), key=lambda indicador: not indicador.activo)
        context['puede_crear_indicador'] = (
            self.object.activo and self.object.periodo.activo and puede_crear_meta(self.request)
        )
        context['puede_estado_indicador'] = obtener_rol(self.request.user) in ROLES_ESTADO_META
        return context


class MetaGuardarMixin(MetaConsultaMixin):
    form_class = MetaForm
    template_name = 'sgr/metas/formulario.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        kwargs['periodo_origen'] = self.get_periodo_origen()
        return kwargs

    def get_periodo_origen(self):
        if 'periodo_pk' not in self.kwargs:
            return None
        periodo = get_object_or_404(Periodo, pk=self.kwargs['periodo_pk'])
        if not periodo.activo:
            raise PermissionDenied('El período está inactivo.')
        return periodo

    def form_valid(self, form):
        nuevo = form.instance.pk is None
        if nuevo:
            form.instance.creado_por = self.request.user
        try:
            with transaction.atomic():
                respuesta = super().form_valid(form)
                registrar_auditoria(
                    self.request, 'crear_meta' if nuevo else 'editar_meta', self.object,
                    f'Se {"creó" if nuevo else "editó"} la meta "{self.object.nombre}" para el '
                    f'período "{self.object.periodo}" en la delegación "{self.object.delegacion}".',
                )
        except ValidationError as error:
            form.add_error(None, ' '.join(error.messages))
            return self.form_invalid(form)
        messages.success(self.request, 'Meta guardada correctamente.')
        return respuesta


class MetaCreateView(MetaGuardarMixin, CreateView):
    def test_func(self):
        return super().test_func() and puede_crear_meta(self.request)


class MetaUpdateView(MetaGuardarMixin, UpdateView):
    def get_object(self, queryset=None):
        meta = super().get_object(queryset)
        if not meta.periodo.activo:
            raise PermissionDenied('Reactive el período antes de modificar sus Metas.')
        return meta


class MetaEstadoView(MetaConsultaMixin, View):
    roles_permitidos = ROLES_ESTADO_META
    http_method_names = ['post']

    def post(self, request, pk):
        with transaction.atomic():
            meta = get_object_or_404(self.get_queryset(), pk=pk)
            if not meta.periodo.activo:
                raise PermissionDenied('Reactive el período antes de modificar sus Metas.')
            valor = request.POST.get('activo')
            if valor not in ('true', 'false'):
                messages.error(request, 'Seleccione un estado válido.')
                return redirect(meta)
            activo = valor == 'true'
            if meta.activo == activo:
                return redirect(meta)
            meta.activo = activo
            try:
                meta.save()
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
                return redirect(meta)
            registrar_auditoria(
                request, 'activar_meta' if activo else 'desactivar_meta', meta,
                f'Se {"activó" if activo else "desactivó"} la meta "{meta.nombre}" para el '
                f'período "{meta.periodo}" en la delegación "{meta.delegacion}".',
            )
        messages.success(request, 'Estado de la Meta actualizado.')
        return redirect(meta)
