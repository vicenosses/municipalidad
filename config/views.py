from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.utils import timezone
from django.views.generic import TemplateView

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from evidencias.models import Evidencia
from sgr.dashboard import construir_dashboard
from usuarios.mixins import obtener_rol
from usuarios.models import Perfil
from usuarios.sesion import get_delegacion_activa


class HomeView(LoginRequiredMixin, TemplateView):
    """Dashboard SGR y contadores dentro del alcance autorizado."""

    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ahora = timezone.now()
        delegacion = get_delegacion_activa(self.request)
        if obtener_rol(self.request.user) == 'administrador' and delegacion is None:
            usuarios = Perfil.objects.filter(activo=True)
            actividades = AtencionCiudadana.objects.all()
            compromisos = Compromiso.objects.all()
            evidencias = Evidencia.objects.all()
        else:
            if delegacion is None:
                usuarios = Perfil.objects.none()
                actividades = AtencionCiudadana.objects.none()
                compromisos = Compromiso.objects.none()
                evidencias = Evidencia.objects.none()
            else:
                usuarios = Perfil.objects.filter(activo=True, delegaciones=delegacion)
                actividades = AtencionCiudadana.objects.filter(delegacion=delegacion)
                compromisos = Compromiso.objects.filter(delegacion=delegacion)
                evidencias = Evidencia.objects.filter(
                    Q(atencion__delegacion=delegacion)
                    | Q(compromiso__delegacion=delegacion)
                )
        context['total_usuarios'] = usuarios.count()
        context['dashboard'] = construir_dashboard(self.request, delegacion)
        context['total_actividades'] = actividades.count()
        context['evidencias_pendientes'] = evidencias.filter(
            estado=Evidencia.Estado.PENDIENTE
        ).count()
        context['compromisos_proximos'] = compromisos.filter(
            estado=Compromiso.Estado.PENDIENTE,
            fecha_hora__gte=ahora,
        ).count()
        return context
