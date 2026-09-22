from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from actividades.models import Actividad
from agenda.models import Compromiso
from evidencias.models import Evidencia
from usuarios.models import Perfil


class HomeView(LoginRequiredMixin, TemplateView):
    """Panel de inicio con contadores del SGR."""

    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ahora = timezone.now()
        context['total_usuarios'] = Perfil.objects.filter(activo=True).count()
        context['total_actividades'] = Actividad.objects.count()
        context['evidencias_pendientes'] = Evidencia.objects.filter(
            estado=Evidencia.Estado.PENDIENTE
        ).count()
        context['compromisos_proximos'] = Compromiso.objects.filter(
            estado=Compromiso.Estado.PENDIENTE,
            fecha_hora__gte=ahora,
        ).count()
        return context
