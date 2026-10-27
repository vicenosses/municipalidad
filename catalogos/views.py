from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from auditoria.utils import registrar_auditoria
from catalogos.forms import ItemMetaForm, SubAtencionForm, TipoAtencionForm
from catalogos.forms import SolicitudCatalogoGeneralForm
from catalogos.models import (
    ItemMeta,
    SolicitudCatalogoGeneral,
    SubAtencion,
    TipoAtencion,
)
from catalogos.permisos import catalogos_editables, catalogos_visibles
from usuarios.sesion import filtrar_contexto_territorial
from catalogos.solicitudes import (
    ConflictoSolicitudCatalogo,
    aprobar_solicitud,
    rechazar_solicitud,
)
from config.listado import FiltroExportMixin
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa


class CatalogoMixin(FiltroExportMixin, RolRequiredMixin):
    roles_permitidos = ('administrador', 'coordinador')


class CatalogoTerritorialMixin(FiltroExportMixin, RolRequiredMixin):
    roles_permitidos = ('administrador', 'coordinador', 'delegado')

    def get_visible_queryset(self, queryset):
        return catalogos_visibles(queryset, self.request)

    def get_editable_queryset(self, queryset):
        return catalogos_editables(queryset, self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['catalogos_editables'] = set(
            self.get_editable_queryset(self.model.objects.all()).values_list(
                'pk',
                flat=True,
            )
        )
        return context


class CatalogosInicioView(RolRequiredMixin, TemplateView):
    template_name = 'catalogos/inicio.html'
    roles_permitidos = ('administrador', 'coordinador', 'delegado')


class ItemListView(CatalogoMixin, ListView):
    model = ItemMeta
    template_name = 'catalogos/items/lista.html'
    context_object_name = 'items'
    search_fields = ('codigo', 'nombre', 'descripcion')
    export_filename = 'items_metas.xlsx'
    export_headers = ('Código', 'Nombre', 'Descripción', 'Estado')
    export_fields = ('codigo', 'nombre', 'descripcion', 'estado_display')


class ItemCreateView(RolRequiredMixin, CreateView):
    model = ItemMeta
    form_class = ItemMetaForm
    template_name = 'catalogos/items/form.html'
    success_url = reverse_lazy('catalogos:item_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de ítem {form.instance.codigo}')
        messages.success(self.request, 'Ítem registrado.')
        return response


class ItemDetailView(RolRequiredMixin, DetailView):
    model = ItemMeta
    template_name = 'catalogos/items/detalle.html'
    roles_permitidos = ('administrador', 'coordinador')


class ItemUpdateView(RolRequiredMixin, UpdateView):
    model = ItemMeta
    form_class = ItemMetaForm
    template_name = 'catalogos/items/form.html'
    success_url = reverse_lazy('catalogos:item_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de ítem {form.instance.codigo}')
        messages.success(self.request, 'Ítem actualizado.')
        return response


class ItemDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador')

    def post(self, request, pk):
        obj = get_object_or_404(ItemMeta, pk=pk)
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de ítem {obj.codigo}')
        messages.success(request, 'Ítem desactivado.')
        return redirect('catalogos:item_lista')


class TipoListView(CatalogoTerritorialMixin, ListView):
    model = TipoAtencion
    template_name = 'catalogos/tipos/lista.html'
    context_object_name = 'tipos'
    search_fields = ('codigo', 'nombre', 'descripcion')
    export_filename = 'tipos_atencion.xlsx'
    export_headers = ('Código', 'Nombre', 'Descripción', 'Estado')
    export_fields = ('codigo', 'nombre', 'descripcion', 'estado_display')

    def get_queryset(self):
        return self.filtrar_queryset(
            self.get_visible_queryset(
                TipoAtencion.objects.select_related('delegacion')
            )
        )


class TipoCreateView(CatalogoTerritorialMixin, CreateView):
    model = TipoAtencion
    form_class = TipoAtencionForm
    template_name = 'catalogos/tipos/form.html'
    success_url = reverse_lazy('catalogos:tipo_lista')
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de tipo {form.instance.codigo}')
        messages.success(self.request, 'Tipo de atención registrado.')
        return response


class TipoDetailView(CatalogoTerritorialMixin, DetailView):
    model = TipoAtencion
    template_name = 'catalogos/tipos/detalle.html'
    def get_queryset(self):
        return self.get_visible_queryset(TipoAtencion.objects.all())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['puede_editar'] = self.get_editable_queryset(
            TipoAtencion.objects.all()
        ).filter(pk=self.object.pk).exists()
        return context


class TipoUpdateView(CatalogoTerritorialMixin, UpdateView):
    model = TipoAtencion
    form_class = TipoAtencionForm
    template_name = 'catalogos/tipos/form.html'
    success_url = reverse_lazy('catalogos:tipo_lista')
    def get_queryset(self):
        return self.get_editable_queryset(TipoAtencion.objects.all())

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de tipo {form.instance.codigo}')
        messages.success(self.request, 'Tipo actualizado.')
        return response


class TipoDesactivarView(CatalogoTerritorialMixin, View):

    def post(self, request, pk):
        obj = get_object_or_404(
            catalogos_editables(TipoAtencion.objects.all(), request),
            pk=pk,
        )
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de tipo {obj.codigo}')
        messages.success(request, 'Tipo de atención desactivado.')
        return redirect('catalogos:tipo_lista')


class SubListView(CatalogoTerritorialMixin, ListView):
    model = SubAtencion
    template_name = 'catalogos/subs/lista.html'
    context_object_name = 'subs'
    search_fields = ('codigo', 'nombre', 'tipo__nombre', 'tipo__codigo')
    export_filename = 'subatenciones.xlsx'
    export_headers = ('Código', 'Nombre', 'Tipo', 'Estado')
    export_fields = ('codigo', 'nombre', 'tipo.nombre', 'estado_display')

    def get_queryset(self):
        return self.filtrar_queryset(
            self.get_visible_queryset(
                SubAtencion.objects.select_related(
                    'tipo',
                    'delegacion',
                    'tipo__delegacion',
                )
            )
        )


class SubCreateView(CatalogoTerritorialMixin, CreateView):
    model = SubAtencion
    form_class = SubAtencionForm
    template_name = 'catalogos/subs/form.html'
    success_url = reverse_lazy('catalogos:sub_lista')
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de subatención {form.instance.codigo}')
        messages.success(self.request, 'Subatención registrada.')
        return response


class SubDetailView(CatalogoTerritorialMixin, DetailView):
    model = SubAtencion
    template_name = 'catalogos/subs/detalle.html'
    def get_queryset(self):
        return self.get_visible_queryset(SubAtencion.objects.select_related('tipo'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['puede_editar'] = self.get_editable_queryset(
            SubAtencion.objects.all()
        ).filter(pk=self.object.pk).exists()
        return context


class SubUpdateView(CatalogoTerritorialMixin, UpdateView):
    model = SubAtencion
    form_class = SubAtencionForm
    template_name = 'catalogos/subs/form.html'
    success_url = reverse_lazy('catalogos:sub_lista')
    def get_queryset(self):
        return self.get_editable_queryset(SubAtencion.objects.select_related('tipo'))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de subatención {form.instance.codigo}')
        messages.success(self.request, 'Subatención actualizada.')
        return response


class SubDesactivarView(CatalogoTerritorialMixin, View):

    def post(self, request, pk):
        obj = get_object_or_404(
            catalogos_editables(SubAtencion.objects.all(), request),
            pk=pk,
        )
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de subatención {obj.codigo}')
        messages.success(request, 'Subatención desactivada.')
        return redirect('catalogos:sub_lista')


class SolicitudCatalogoCreateView(RolRequiredMixin, CreateView):
    form_class = SolicitudCatalogoGeneralForm
    template_name = 'catalogos/solicitudes/form.html'
    success_url = reverse_lazy('catalogos:solicitud_lista')
    roles_permitidos = ('coordinador', 'delegado')
    tipo_solicitud = None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        kwargs['tipo_solicitud'] = self.tipo_solicitud
        return kwargs

    @transaction.atomic
    def form_valid(self, form):
        if get_delegacion_activa(self.request) is None:
            form.add_error(
                None,
                'Debe tener una delegación activa autorizada para solicitar un catálogo.',
            )
            return self.form_invalid(form)
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear_solicitud_catalogo_general',
            form.instance,
            (
                f'Solicitud {form.instance.get_tipo_solicitud_display().lower()} '
                f'general: {form.instance.codigo} — {form.instance.nombre}'
            ),
        )
        messages.success(self.request, 'Solicitud general enviada al Administrador.')
        return response


class SolicitudCategoriaCreateView(SolicitudCatalogoCreateView):
    tipo_solicitud = SolicitudCatalogoGeneral.Tipo.CATEGORIA


class SolicitudSubcategoriaCreateView(SolicitudCatalogoCreateView):
    tipo_solicitud = SolicitudCatalogoGeneral.Tipo.SUBCATEGORIA


class SolicitudCatalogoListView(RolRequiredMixin, ListView):
    model = SolicitudCatalogoGeneral
    template_name = 'catalogos/solicitudes/lista.html'
    context_object_name = 'solicitudes'
    roles_permitidos = ('administrador', 'coordinador', 'delegado')

    def get_queryset(self):
        queryset = SolicitudCatalogoGeneral.objects.select_related(
            'solicitante',
            'delegacion_solicitante',
            'decidido_por',
            'categoria_padre',
        )
        queryset = filtrar_contexto_territorial(queryset, self.request, 'delegacion_solicitante')
        if obtener_rol(self.request.user) == 'administrador':
            return queryset
        return queryset.filter(solicitante=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['es_administrador'] = (
            obtener_rol(self.request.user) == 'administrador'
        )
        return context


class SolicitudCatalogoDecisionView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)
    success_url = reverse_lazy('catalogos:solicitud_lista')

    @transaction.atomic
    def post(self, request, pk):
        solicitud = get_object_or_404(
            filtrar_contexto_territorial(SolicitudCatalogoGeneral.objects.select_related(
                'solicitante',
                'categoria_padre',
            ), request, 'delegacion_solicitante'),
            pk=pk,
        )
        accion = request.POST.get('accion')
        try:
            if accion == 'aprobar':
                aprobar_solicitud(solicitud, request.user)
                registrar_auditoria(
                    request,
                    'aprobar_solicitud_catalogo_general',
                    solicitud,
                    (
                        f'Solicitud de {solicitud.get_tipo_solicitud_display().lower()} '
                        f'aprobada: {solicitud.codigo} — {solicitud.nombre}; '
                        f'solicitante: {solicitud.solicitante_id}'
                    ),
                )
                messages.success(request, 'Solicitud aprobada y catálogo publicado.')
            elif accion == 'rechazar':
                motivo = request.POST.get('motivo_decision', '').strip()
                rechazar_solicitud(solicitud, request.user, motivo)
                registrar_auditoria(
                    request,
                    'rechazar_solicitud_catalogo_general',
                    solicitud,
                    (
                        f'Solicitud de {solicitud.get_tipo_solicitud_display().lower()} '
                        f'rechazada: {solicitud.codigo} — {solicitud.nombre}; '
                        f'solicitante: {solicitud.solicitante_id}'
                    ),
                )
                messages.success(request, 'Solicitud rechazada.')
            else:
                messages.error(request, 'Acción de decisión no válida.')
        except ConflictoSolicitudCatalogo as error:
            messages.error(request, error.messages[0])
        return redirect(self.success_url)
