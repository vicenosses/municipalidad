from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, FormView, ListView

from atenciones.models import AtencionCiudadana
from auditoria.utils import registrar_auditoria
from evidencias.forms import EvidenciaAtencionForm, EvidenciaForm, ValidacionEvidenciaForm
from evidencias.models import Evidencia
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.sesion import get_delegacion_activa


class EvidenciaListView(LoginRequiredMixin, ListView):
    model = Evidencia
    template_name = 'evidencias/lista.html'
    context_object_name = 'evidencias'

    def get_queryset(self):
        qs = Evidencia.objects.select_related(
            'actividad', 'atencion', 'subido_por', 'validado_por'
        )
        rol = obtener_rol(self.request.user)
        if rol == 'administrador':
            return qs
        if rol in ('coordinador', 'verificador'):
            delegacion = get_delegacion_activa(self.request)
            if delegacion:
                return qs.filter(
                    Q(actividad__delegacion=delegacion) | Q(subido_por=self.request.user)
                )
            return qs.none()
        return qs.filter(subido_por=self.request.user)


class EvidenciaCreateView(RolRequiredMixin, CreateView):
    form_class = EvidenciaForm
    template_name = 'evidencias/form.html'
    success_url = reverse_lazy('evidencias:lista')
    roles_permitidos = ('administrador', 'coordinador', 'funcionario', 'delegado')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.subido_por = self.request.user
        response = super().form_valid(form)
        registrar_auditoria(
            self.request,
            'crear',
            form.instance,
            f'Subida de evidencia {form.instance.codigo_respaldo}',
        )
        messages.success(
            self.request,
            f'Evidencia cargada. Código de respaldo: {form.instance.codigo_respaldo}',
        )
        return response


class EvidenciaAtencionCreateView(LoginRequiredMixin, FormView):
    form_class = EvidenciaAtencionForm
    template_name = 'evidencias/atencion_form.html'

    def get_atencion(self):
        if not hasattr(self, '_atencion'):
            self._atencion = get_object_or_404(
                AtencionCiudadana,
                pk=self.kwargs['pk'],
                responsable=self.request.user,
            )
        return self._atencion

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atencion'] = self.get_atencion()
        context['max_image_mb'] = getattr(settings, 'EVIDENCIA_MAX_IMAGE_MB', 10)
        context['max_video_mb'] = getattr(settings, 'EVIDENCIA_MAX_VIDEO_MB', 100)
        context['max_batch_mb'] = getattr(settings, 'EVIDENCIA_MAX_BATCH_MB', 250)
        return context

    def form_valid(self, form):
        atencion = self.get_atencion()
        evidencias = []
        with transaction.atomic():
            for archivo in form.cleaned_data['archivos']:
                evidencia = Evidencia(
                    atencion=atencion,
                    subido_por=self.request.user,
                    estado=Evidencia.Estado.PENDIENTE,
                    archivo=archivo,
                )
                evidencia.save()
                evidencias.append(evidencia)
                registrar_auditoria(
                    self.request,
                    'crear',
                    evidencia,
                    f'Evidencia {evidencia.identificador} agregada a atención {atencion.pk}',
                )
        messages.success(self.request, f'Se agregaron {len(evidencias)} evidencias pendientes.')
        return redirect('atenciones:detalle', pk=atencion.pk)


class EvidenciaArchivoView(LoginRequiredMixin, View):
    """Entrega archivos después de verificar permisos en cada solicitud."""

    def get(self, request, pk):
        evidencia = get_object_or_404(
            Evidencia.objects.select_related('actividad', 'atencion', 'subido_por'),
            pk=pk,
        )
        if not self.puede_ver(request, evidencia):
            raise Http404
        try:
            archivo = evidencia.archivo.open('rb')
        except FileNotFoundError as error:
            raise Http404 from error
        extension = evidencia.archivo.name.rsplit('.', 1)[-1].lower()
        respuesta = FileResponse(
            archivo,
            as_attachment=False,
            filename=f'{evidencia.identificador}.{extension}',
            content_type=evidencia.content_type,
        )
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta

    @staticmethod
    def puede_ver(request, evidencia):
        if obtener_rol(request.user) == 'administrador':
            return True
        if evidencia.subido_por_id == request.user.pk:
            return True
        if evidencia.atencion_id:
            if evidencia.atencion.responsable_id == request.user.pk:
                return True
            delegacion = get_delegacion_activa(request)
            return bool(
                evidencia.estado == Evidencia.Estado.APROBADA
                and obtener_rol(request.user) in ('coordinador', 'verificador')
                and delegacion
                and evidencia.atencion.delegacion_id == delegacion.pk
            )
        if obtener_rol(request.user) in ('coordinador', 'verificador'):
            delegacion = get_delegacion_activa(request)
            return bool(
                delegacion
                and evidencia.actividad_id
                and evidencia.actividad.delegacion_id == delegacion.pk
            )
        return False


class EvidenciaValidarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador', 'verificador')

    def get_evidencia(self, request, pk):
        qs = Evidencia.objects.select_related('actividad', 'atencion', 'subido_por')
        if obtener_rol(request.user) != 'administrador':
            qs = qs.exclude(atencion__isnull=False)
            delegacion = get_delegacion_activa(request)
            if delegacion is None:
                return get_object_or_404(qs.none(), pk=pk)
            qs = qs.filter(actividad__delegacion=delegacion)
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        evidencia = self.get_evidencia(request, pk)
        form = ValidacionEvidenciaForm(initial={'comentario': evidencia.comentario_validacion})
        return render(request, 'evidencias/validar.html', {'evidencia': evidencia, 'form': form})

    def post(self, request, pk):
        evidencia = self.get_evidencia(request, pk)
        if evidencia.atencion_id and obtener_rol(request.user) != 'administrador':
            raise PermissionDenied
        if evidencia.estado != Evidencia.Estado.PENDIENTE:
            messages.error(request, 'Esta evidencia ya fue validada.')
            return redirect('evidencias:lista')
        form = ValidacionEvidenciaForm(request.POST)
        if not form.is_valid():
            return render(request, 'evidencias/validar.html', {'evidencia': evidencia, 'form': form})

        accion = request.POST.get('accion')
        if accion not in ('aprobar', 'rechazar'):
            messages.error(request, 'Acción de validación no válida.')
            return redirect('evidencias:validar', pk=pk)

        evidencia.comentario_validacion = form.cleaned_data.get('comentario', '')
        evidencia.validado_por = request.user
        evidencia.fecha_validacion = timezone.now()
        evidencia.estado = (
            Evidencia.Estado.APROBADA if accion == 'aprobar' else Evidencia.Estado.RECHAZADA
        )
        evidencia.save()
        registrar_auditoria(
            request,
            'validar',
            evidencia,
            f'Evidencia {evidencia.codigo_respaldo} {evidencia.get_estado_display().lower()}',
        )
        messages.success(request, f'Evidencia {evidencia.get_estado_display().lower()}.')
        return redirect('evidencias:lista')
