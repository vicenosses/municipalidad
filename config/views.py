from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from agenda.models import Compromiso
from sgr.dashboard import construir_dashboard, calcular_semaforo
from sgr.forms_informes import InformeFiltroForm
from sgr.asignaciones import calcular_resultado_asignacion
from sgr.models import AsignacionMeta
from usuarios.mixins import obtener_rol
from usuarios.models import Perfil
from usuarios.sesion import get_delegacion_activa


class HomeView(LoginRequiredMixin, TemplateView):
    """Dashboard SGR y contadores dentro del alcance autorizado."""

    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = InformeFiltroForm(self.request.GET, request=self.request)
        if form.is_valid():
            filtros = form.cleaned_data
            dashboard = construir_dashboard(
                self.request,
                periodo=filtros.get('periodo'),
                delegacion=filtros.get('delegacion'),
                funcionario=filtros.get('funcionario'),
                meta=filtros.get('meta'),
            )
        else:
            dashboard = construir_dashboard(self.request)
            dashboard.update(
                periodo=None, mensaje='Revise los filtros seleccionados para consultar el dashboard.',
                esperado=None, filas=[], total_metas=0, metas_calculables=0,
                metas_incompletas=0, conteos=dict(verde=0, naranjo=0, rojo=0, sin_datos=0),
                asignaciones=[], actividades=[], compromisos=[], evidencias=[],
                cartas=[], gestiones_sociales=[], hitos=[],
            )
        context['dashboard_form'] = form
        context['dashboard'] = dashboard
        delegacion = filtros.get('delegacion') if form.is_valid() else None
        delegacion = delegacion or get_delegacion_activa(self.request)
        usuarios = Perfil.objects.filter(activo=True)
        if delegacion is not None:
            usuarios = usuarios.filter(delegaciones=delegacion)
        elif obtener_rol(self.request.user) != 'administrador':
            usuarios = usuarios.none()
        if form.is_valid() and filtros.get('funcionario'):
            usuarios = usuarios.filter(usuario=filtros['funcionario'])
        context['total_usuarios'] = usuarios.distinct().count()
        context['metas_individuales'] = []
        periodo = dashboard['periodo']
        if periodo and delegacion and obtener_rol(self.request.user) in ('funcionario', 'verificador'):
            asignaciones = AsignacionMeta.objects.filter(
                funcionario=self.request.user, activa=True, meta__activo=True,
                meta__periodo=periodo, meta__delegacion=delegacion,
            ).select_related('meta__periodo', 'funcionario')
            if form.is_valid() and filtros.get('meta'):
                asignaciones = asignaciones.filter(meta=filtros['meta'])
            for asignacion in asignaciones:
                resultado = calcular_resultado_asignacion(asignacion)
                context['metas_individuales'].append({
                    'resultado': resultado,
                    'semaforo': calcular_semaforo(resultado.cumplimiento_aplicable,
                                                 context['dashboard']['esperado']),
                })
        context['total_actividades'] = len(dashboard['actividades'])
        context['evidencias_pendientes'] = sum(
            evidencia.estado == evidencia.Estado.PENDIENTE
            for evidencia in dashboard['evidencias']
        )
        context['compromisos_proximos'] = sum(
            compromiso.estado == Compromiso.Estado.PENDIENTE
            and compromiso.proximo_a_vencer
            for compromiso in dashboard['compromisos']
        )
        context['compromisos_vencidos'] = sum(
            compromiso.esta_vencido for compromiso in dashboard['compromisos']
        )
        context['tubo_abierto'] = sum(
            not compromiso.es_terminal for compromiso in dashboard['compromisos']
        )
        context['total_cartas'] = len(dashboard['cartas'])
        context['total_gestiones_sociales'] = len(dashboard['gestiones_sociales'])
        context['total_hitos'] = len(dashboard['hitos'])
        context['hitos_pendientes'] = sum(
            hito.estado in ('pendiente', 'en_proceso') for hito in dashboard['hitos']
        )
        context['hitos_vencidos'] = sum(
            hito.estado in ('pendiente', 'en_proceso')
            and hito.fecha_programada < dashboard['fecha_corte']
            for hito in dashboard['hitos']
        )
        context['evidencias_aprobadas'] = sum(
            evidencia.estado == evidencia.Estado.APROBADA
            for evidencia in dashboard['evidencias']
        )
        context['evidencias_rechazadas'] = sum(
            evidencia.estado == evidencia.Estado.RECHAZADA
            for evidencia in dashboard['evidencias']
        )
        return context
