"""Exportación de revisión previa: no cierra ni congela el trimestre."""
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font
from django.http import HttpResponse
from django.utils import timezone

from sgr.models import AporteIndicador, AsignacionMeta, Meta
from sgr.preparacion_cierre import diagnosticar_periodo


def _texto(valor):
    valor = str(valor or '')
    return "'" + valor if valor.lstrip().startswith(('=', '+', '-', '@')) else valor


def exportar_revision_cierre(periodo):
    revision = diagnosticar_periodo(periodo)
    libro = Workbook()
    resumen = libro.active
    resumen.title = 'Resumen'
    for fila in (('Revisión previa al cierre', 'PROVISIONAL: no congela resultados'),
                 ('Período', _texto(periodo.nombre)),
                 ('Desde', periodo.fecha_inicio), ('Hasta', periodo.fecha_fin),
                 ('Generado', timezone.localtime().strftime('%d/%m/%Y %H:%M')),
                 ('Metas activas', revision['metas_activas']),
                 ('Metas sin asignación', revision['metas_sin_asignacion']),
                 ('Aportes pendientes o en corrección', revision['pendientes']),
                 ('Asignaciones con objetivo inválido', revision['asignaciones_invalidas']),
                 ('Ponderaciones', 'Suma requerida pendiente de confirmación')):
        resumen.append(fila)
    resultados = libro.create_sheet('Resultados individuales')
    resultados.append(['Funcionario', 'Meta', 'Delegación', 'Actividades aprobadas', 'Objetivo',
                       'Cumplimiento aplicable (%)', 'Ponderación asignada (%)', 'Resultado ponderado (%)'])
    for resultado in revision['resultados']:
        a = resultado.asignacion
        resultados.append([_texto(a.funcionario.get_full_name() or a.funcionario.username),
            _texto(a.meta.nombre), _texto(a.meta.delegacion.nombre), resultado.cantidad,
            float(a.cantidad_objetivo), float(resultado.cumplimiento_aplicable), float(a.ponderacion),
            float(resultado.resultado_ponderado)])
    pendientes = libro.create_sheet('Aportes pendientes')
    pendientes.append(['Actividad', 'Meta', 'Delegación', 'Estado', 'Fecha'])
    qs = AporteIndicador.objects.filter(indicador__meta__periodo=periodo, estado__in=(
        AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.REQUIERE_CORRECCION,
    )).select_related('actividad', 'indicador__meta__delegacion').order_by('actividad__fecha', 'pk')
    for aporte in qs:
        pendientes.append([_texto(aporte.actividad.titulo), _texto(aporte.indicador.meta.nombre),
                           _texto(aporte.indicador.meta.delegacion.nombre), aporte.get_estado_display(), aporte.actividad.fecha])
    metas = libro.create_sheet('Metas sin asignación')
    metas.append(['Meta', 'Delegación'])
    asignadas = AsignacionMeta.objects.filter(meta__periodo=periodo, meta__activo=True, activa=True)
    for meta in Meta.objects.filter(periodo=periodo, activo=True).exclude(
            pk__in=asignadas.values('meta_id')).select_related('delegacion').order_by('nombre', 'pk'):
        metas.append([_texto(meta.nombre), _texto(meta.delegacion.nombre)])
    for hoja in libro:
        hoja.freeze_panes = 'A2'
        for celda in hoja[1]:
            celda.font = Font(bold=True)
        for columna in hoja.columns:
            hoja.column_dimensions[columna[0].column_letter].width = min(48, max(18, max(len(str(c.value or '')) for c in columna) + 2))
    salida = BytesIO()
    libro.save(salida)
    respuesta = HttpResponse(salida.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="revision-periodo-{periodo.pk}.xlsx"'
    respuesta['Cache-Control'] = 'private, no-store'
    return respuesta
