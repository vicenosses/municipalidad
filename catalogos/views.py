from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from catalogos.forms import ItemMetaForm, SubAtencionForm, TipoAtencionForm
from catalogos.models import ItemMeta, SubAtencion, TipoAtencion
from config.listado import FiltroExportMixin
from usuarios.mixins import RolRequiredMixin


class CatalogoMixin(FiltroExportMixin, RolRequiredMixin):
    roles_permitidos = ('administrador', 'coordinador')


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


class TipoListView(CatalogoMixin, ListView):
    model = TipoAtencion
    template_name = 'catalogos/tipos/lista.html'
    context_object_name = 'tipos'
    search_fields = ('codigo', 'nombre', 'descripcion')
    export_filename = 'tipos_atencion.xlsx'
    export_headers = ('Código', 'Nombre', 'Descripción', 'Estado')
    export_fields = ('codigo', 'nombre', 'descripcion', 'estado_display')


class TipoCreateView(RolRequiredMixin, CreateView):
    model = TipoAtencion
    form_class = TipoAtencionForm
    template_name = 'catalogos/tipos/form.html'
    success_url = reverse_lazy('catalogos:tipo_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de tipo {form.instance.codigo}')
        messages.success(self.request, 'Tipo de atención registrado.')
        return response


class TipoDetailView(RolRequiredMixin, DetailView):
    model = TipoAtencion
    template_name = 'catalogos/tipos/detalle.html'
    roles_permitidos = ('administrador', 'coordinador')


class TipoUpdateView(RolRequiredMixin, UpdateView):
    model = TipoAtencion
    form_class = TipoAtencionForm
    template_name = 'catalogos/tipos/form.html'
    success_url = reverse_lazy('catalogos:tipo_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de tipo {form.instance.codigo}')
        messages.success(self.request, 'Tipo actualizado.')
        return response


class TipoDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador')

    def post(self, request, pk):
        obj = get_object_or_404(TipoAtencion, pk=pk)
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de tipo {obj.codigo}')
        messages.success(request, 'Tipo de atención desactivado.')
        return redirect('catalogos:tipo_lista')


class SubListView(CatalogoMixin, ListView):
    model = SubAtencion
    template_name = 'catalogos/subs/lista.html'
    context_object_name = 'subs'
    search_fields = ('codigo', 'nombre', 'tipo__nombre', 'tipo__codigo')
    export_filename = 'subatenciones.xlsx'
    export_headers = ('Código', 'Nombre', 'Tipo', 'Estado')
    export_fields = ('codigo', 'nombre', 'tipo.nombre', 'estado_display')

    def get_queryset(self):
        return self.filtrar_queryset(SubAtencion.objects.select_related('tipo'))


class SubCreateView(RolRequiredMixin, CreateView):
    model = SubAtencion
    form_class = SubAtencionForm
    template_name = 'catalogos/subs/form.html'
    success_url = reverse_lazy('catalogos:sub_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'crear', form.instance, f'Alta de subatención {form.instance.codigo}')
        messages.success(self.request, 'Subatención registrada.')
        return response


class SubDetailView(RolRequiredMixin, DetailView):
    model = SubAtencion
    template_name = 'catalogos/subs/detalle.html'
    roles_permitidos = ('administrador', 'coordinador')


class SubUpdateView(RolRequiredMixin, UpdateView):
    model = SubAtencion
    form_class = SubAtencionForm
    template_name = 'catalogos/subs/form.html'
    success_url = reverse_lazy('catalogos:sub_lista')
    roles_permitidos = ('administrador', 'coordinador')

    def form_valid(self, form):
        response = super().form_valid(form)
        registrar_auditoria(self.request, 'editar', form.instance, f'Edición de subatención {form.instance.codigo}')
        messages.success(self.request, 'Subatención actualizada.')
        return response


class SubDesactivarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador')

    def post(self, request, pk):
        obj = get_object_or_404(SubAtencion, pk=pk)
        obj.activo = False
        obj.save(update_fields=['activo'])
        registrar_auditoria(request, 'desactivar', obj, f'Desactivación de subatención {obj.codigo}')
        messages.success(request, 'Subatención desactivada.')
        return redirect('catalogos:sub_lista')
