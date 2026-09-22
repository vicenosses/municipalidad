from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView

from auditoria.utils import registrar_auditoria
from evidencias.forms import EvidenciaForm, ValidacionEvidenciaForm
from evidencias.models import Evidencia
from usuarios.mixins import RolRequiredMixin, obtener_rol


class EvidenciaListView(LoginRequiredMixin, ListView):
    model = Evidencia
    template_name = 'evidencias/lista.html'
    context_object_name = 'evidencias'

    def get_queryset(self):
        qs = Evidencia.objects.select_related('actividad', 'subido_por', 'validado_por')
        rol = obtener_rol(self.request.user)
        if rol in ('administrador', 'coordinador', 'verificador'):
            return qs
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


class EvidenciaValidarView(RolRequiredMixin, View):
    roles_permitidos = ('administrador', 'coordinador', 'verificador')

    def get(self, request, pk):
        evidencia = get_object_or_404(Evidencia, pk=pk)
        form = ValidacionEvidenciaForm(initial={'comentario': evidencia.comentario_validacion})
        return render(request, 'evidencias/validar.html', {'evidencia': evidencia, 'form': form})

    def post(self, request, pk):
        evidencia = get_object_or_404(Evidencia, pk=pk)
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
