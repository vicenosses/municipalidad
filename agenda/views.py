from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from agenda.forms import CompromisoFiltroForm, CompromisoForm
from agenda.models import Compromiso, HistorialCompromiso
from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa

User = get_user_model()


def compromisos_visibles(request):
    qs = Compromiso.objects.select_related(
        'responsable', 'delegacion'
    ).prefetch_related('actividades', 'historial__realizado_por')
    rol = obtener_rol(request.user)
    if rol == 'administrador':
        return qs
    delegacion = get_delegacion_activa(request)
    if delegacion:
        return qs.filter(
            Q(delegacion=delegacion) | Q(responsable=request.user)
        ).distinct()
    if rol == 'coordinador':
        return qs.none()
    return qs.filter(responsable=request.user)


def puede_gestionar(user):
    return user.is_superuser or obtener_rol(user) in ('administrador', 'coordinador')


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
        context['puede_crear'] = obtener_rol(self.request.user) in (
            'administrador', 'coordinador', 'delegado'
        ) or self.request.user.is_superuser
        return context


class CompromisoCreateView(RolRequiredMixin, CreateView):
    form_class = CompromisoForm
    template_name = 'agenda/form.html'
    success_url = reverse_lazy('agenda:lista')
    roles_permitidos = ('administrador', 'coordinador', 'delegado')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        delegacion = get_delegacion_activa(self.request)
        kwargs.update(
            user=self.request.user,
            delegacion=delegacion,
            delegaciones=[delegacion] if delegacion else [],
            es_creacion=True,
        )
        return kwargs

    def form_valid(self, form):
        delegacion = get_delegacion_activa(self.request)
        if delegacion is None:
            form.add_error(None, 'Su perfil no tiene una delegación asignada.')
            return self.form_invalid(form)
        form.instance.delegacion = delegacion
        form.instance.estado = Compromiso.Estado.INGRESADO
        with transaction.atomic():
            response = super().form_valid(form)
            HistorialCompromiso.objects.create(
                compromiso=self.object,
                campo='creacion',
                valor_nuevo=self.object.get_estado_display(),
                realizado_por=self.request.user,
            )
            registrar_auditoria(
                self.request,
                'crear',
                self.object,
                f'Alta de compromiso: {self.object.titulo}',
            )
        messages.success(self.request, 'Compromiso ingresado a la agenda.')
        return response


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
        context['puede_editar'] = (
            puede_gestionar(self.request.user)
            or compromiso.responsable_id == self.request.user.pk
        )
        context['puede_subir_evidencia'] = context['puede_editar']
        return context


class CompromisoUpdateView(LoginRequiredMixin, UpdateView):
    model = Compromiso
    form_class = CompromisoForm
    template_name = 'agenda/form.html'
    context_object_name = 'compromiso'

    def get_queryset(self):
        return compromisos_visibles(self.request)

    def get_object(self, queryset=None):
        compromiso = super().get_object(queryset)
        if not (
            puede_gestionar(self.request.user)
            or compromiso.responsable_id == self.request.user.pk
        ):
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
