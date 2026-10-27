from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from sgr.exportacion_informes import exportar_informe_excel
from sgr.forms_informes import InformeFiltroForm
from sgr.informes import autorizar_informe, construir_informe


class InformeSGRView(LoginRequiredMixin, TemplateView):
    template_name = 'sgr/informes/resumen.html'

    def get(self, request, *args, **kwargs):
        autorizar_informe(request)
        form = InformeFiltroForm(request.GET)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form, informe=None), status=400)
        informe = construir_informe(request, periodo=form.cleaned_data['periodo'])
        if request.GET.get('export') == 'xlsx' and informe['periodo'] and not informe['mensaje']:
            return exportar_informe_excel(informe)
        parametros = request.GET.copy()
        parametros.pop('export', None)
        parametros['export'] = 'xlsx'
        return self.render_to_response(self.get_context_data(
            form=form, informe=informe, export_query=parametros.urlencode()))
