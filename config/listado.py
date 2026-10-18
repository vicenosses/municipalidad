from datetime import datetime
from io import BytesIO

from django.db.models import Q
from django.http import HttpResponse
from django.utils.timezone import is_aware, localtime
from openpyxl import Workbook


def valor_attr(obj, path):
    actual = obj
    for parte in path.split('.'):
        if actual is None:
            return ''
        actual = getattr(actual, parte, '')
        if callable(actual):
            try:
                actual = actual()
            except TypeError:
                pass
    if actual is True:
        return 'Sí'
    if actual is False:
        return 'No'
    if isinstance(actual, datetime) and is_aware(actual):
        return localtime(actual).replace(tzinfo=None)
    return '' if actual is None else actual


class FiltroExportMixin:
    """Búsqueda parcial, paginación, total y exportar Excel conservando filtros."""

    paginate_by = 10
    search_fields = ()
    export_filename = 'exportacion.xlsx'
    export_headers = ()
    export_fields = ()

    def get_search_query(self):
        return self.request.GET.get('q', '').strip()

    def filtrar_queryset(self, qs):
        q = self.get_search_query()
        if q and self.search_fields:
            consulta = Q()
            for campo in self.search_fields:
                consulta |= Q(**{f'{campo}__icontains': q})
            qs = qs.filter(consulta)
        return qs

    def get_queryset(self):
        return self.filtrar_queryset(super().get_queryset())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['usar_swal_mensajes'] = True
        params = self.request.GET.copy()
        params.pop('page', None)
        params.pop('export', None)
        context['q'] = self.get_search_query()
        context['querystring'] = params.urlencode()
        paginator = context.get('paginator')
        if paginator:
            context['total_resultados'] = paginator.count
        else:
            context['total_resultados'] = self.get_queryset().count()
        return context

    def get(self, request, *args, **kwargs):
        if request.GET.get('export') == 'xlsx':
            return self.exportar_excel()
        return super().get(request, *args, **kwargs)

    def exportar_excel(self):
        qs = self.get_queryset()
        libro = Workbook()
        hoja = libro.active
        hoja.title = 'Datos'
        hoja.append(list(self.export_headers))
        for obj in qs:
            hoja.append([valor_attr(obj, campo) for campo in self.export_fields])
        buffer = BytesIO()
        libro.save(buffer)
        buffer.seek(0)
        respuesta = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        respuesta['Content-Disposition'] = f'attachment; filename="{self.export_filename}"'
        return respuesta
