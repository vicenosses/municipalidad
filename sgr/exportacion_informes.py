"""XLSX de valores ya calculados, sin fórmulas ni nuevas consultas."""
from io import BytesIO
from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font

LIMITACIONES = (
    'Resultados vigentes al consultar; no es una reconstrucción histórica. '
    'Calendario inclusivo; sin descontar feriados, licencias, vacaciones, emergencias ni compensatorios. '
    'Los indicadores inactivos no se agregan. Los valores no calculables quedan vacíos con estado explícito. '
    'Los porcentajes se expresan en escala 0 a 100; el cumplimiento individual tiene tope de 120%. '
    'El semáforo representa solo la cobertura calculable; la regla especial del tubo queda fuera.'
)


def _agregar_fila(hoja, valores):
    valores = [
        timezone.make_naive(valor) if isinstance(valor, datetime) and timezone.is_aware(valor) else valor
        for valor in valores
    ]
    hoja.append(valores)
    # Los nombres y observaciones son texto, incluso si comienzan con '='.
    for celda in hoja[hoja.max_row]:
        if isinstance(celda.value, str):
            celda.data_type = 's'


def exportar_informe_excel(informe):
    libro = Workbook()
    metas = libro.active
    metas.title = 'Metas'
    indicadores = libro.create_sheet('Indicadores')
    asignaciones = libro.create_sheet('Funcionarios')
    actividades = libro.create_sheet('Actividades')
    tubo = libro.create_sheet('Tubo')
    evidencias = libro.create_sheet('Evidencias')
    cartas = libro.create_sheet('Cartas')
    gestiones = libro.create_sheet('Gestion social')
    hitos = libro.create_sheet('Hitos')
    periodo = informe['periodo']
    hojas = (metas, indicadores, asignaciones, actividades, tubo, evidencias, cartas, gestiones, hitos)
    for hoja in hojas:
        for fila in (
            ['Informe SGR', periodo.nombre],
            ['Período', periodo.fecha_inicio, periodo.fecha_fin, 'Activo' if periodo.activo else 'Inactivo'],
            ['Contexto territorial', str(informe['contexto_territorial'])],
            ['Fecha de consulta', informe['fecha_corte']],
            ['Limitaciones', LIMITACIONES],
        ):
            _agregar_fila(hoja, fila)
        hoja.append([])
        hoja.freeze_panes = 'C8'
    _agregar_fila(metas, ['Meta', 'Delegación', 'Cumplimiento normalizado (%)',
        'Resultado ponderado bruto (pp)', 'Cobertura calculable (%)', 'Ponderación asignada (%)',
        'Ponderación pendiente (%)', 'Configuración completa', 'Indicadores sin ponderación',
        'Indicadores sin cumplimiento numérico', 'Indicadores sin límite', 'Avance esperado (%)', 'Semáforo'])
    _agregar_fila(indicadores, ['Meta', 'Delegación', 'Indicador', 'Activo', 'Unidad', 'Sentido',
        'Objetivo', 'Resultado actual', 'Cumplimiento (%)', 'Estado de cumplimiento',
        'Ponderación (%)', 'Resultado ponderado (pp)', 'Estado de ponderación', 'Base utilizada',
        'Sin valor validado', 'Sin duración calculable', 'Observaciones'])
    _agregar_fila(asignaciones, ['Funcionario', 'Delegación', 'Meta', 'Período', 'Objetivo',
        'Ponderación (%)', 'Aportes aprobados y ponderados', 'Cumplimiento aplicable (%)',
        'Resultado ponderado (%)'])
    _agregar_fila(actividades, ['Fecha', 'Título', 'Responsable', 'Delegación', 'Territorio',
        'Origen', 'Tipo', 'Estado', 'Va al tubo', 'Avance (%)', 'Meta', 'Estado del aporte',
        'Estado de evidencias', 'Resultado'])
    _agregar_fila(tubo, ['Código', 'Compromiso', 'Solicitante', 'Fecha compromiso', 'Responsable',
        'Delegación', 'Estado', 'Vencido', 'Observaciones'])
    _agregar_fila(evidencias, ['Identificador', 'Fecha de carga', 'Registro', 'Estado',
        'Tipo de archivo', 'Autor', 'Revisor', 'Observación'])
    _agregar_fila(cartas, ['Fecha de ingreso', 'Código', 'Asunto', 'Responsable',
        'Delegación', 'Área derivada', 'Estado', 'Fecha compromiso', 'Fecha respuesta',
        'Fecha cierre'])
    _agregar_fila(gestiones, ['Fecha de ingreso', 'Código', 'Gestión', 'Beneficiario',
        'Responsable', 'Delegación', 'Estado', 'Fecha compromiso', 'Fecha cierre',
        'Días de atención', 'Resultado'])
    _agregar_fila(hitos, ['Fecha programada', 'Código', 'Hito', 'Responsable',
        'Delegación', 'Territorio', 'Periodicidad', 'Estado', 'Fecha completada'])
    for fila in informe['filas']:
        resultado = fila.resultado
        _agregar_fila(metas, [fila.meta.nombre, str(fila.meta.delegacion),
            resultado.cumplimiento_normalizado, resultado.resultado_ponderado_bruto,
            resultado.cobertura_calculable, resultado.ponderacion_asignada, resultado.ponderacion_pendiente,
            'Sí' if resultado.configuracion_completa else 'No', resultado.sin_ponderacion,
            resultado.sin_resultado, resultado.sin_limite, informe['esperado'], fila.semaforo.texto])
        for ponderado in resultado.indicadores:
            indicador, metrica = ponderado.indicador, ponderado.metrica
            _agregar_fila(indicadores, [fila.meta.nombre, str(fila.meta.delegacion), indicador.nombre,
                'Sí' if indicador.activo else 'No', indicador.unidad_display, metrica.sentido,
                metrica.objetivo, metrica.resultado, metrica.cumplimiento.porcentaje,
                metrica.cumplimiento.estado.value, ponderado.ponderacion, ponderado.resultado_ponderado,
                ponderado.estado, metrica.base_utilizada, metrica.sin_valor_validado,
                metrica.sin_duracion_calculable, ' '.join(metrica.observaciones)])
    for resultado in informe['asignaciones']:
        asignacion = resultado.asignacion
        _agregar_fila(asignaciones, [
            asignacion.funcionario.get_full_name() or asignacion.funcionario.get_username(),
            str(asignacion.meta.delegacion), asignacion.meta.nombre, periodo.nombre,
            asignacion.cantidad_objetivo, asignacion.ponderacion, resultado.cantidad,
            resultado.cumplimiento_aplicable, resultado.resultado_ponderado,
        ])
    for actividad in informe['actividades']:
        aporte = getattr(actividad, 'aporte_indicador', None)
        _agregar_fila(actividades, [
            actividad.fecha, actividad.titulo,
            actividad.responsable.get_full_name() or actividad.responsable.get_username(),
            str(actividad.delegacion), str(actividad.territorio or ''),
            actividad.origen, actividad.tipo.nombre, actividad.get_estado_display(),
            'Sí' if actividad.va_al_tubo else 'No', actividad.avance,
            aporte.indicador.meta.nombre if aporte else '',
            aporte.get_estado_display() if aporte else 'Sin aporte',
            actividad.etiqueta_estado_evidencias, actividad.resultado,
        ])
    for compromiso in informe['compromisos']:
        _agregar_fila(tubo, [
            compromiso.codigo, compromiso.titulo, compromiso.solicitante,
            compromiso.fecha_hora, compromiso.responsable.get_full_name() or compromiso.responsable.get_username(),
            str(compromiso.delegacion), compromiso.get_estado_display(),
            'Sí' if compromiso.esta_vencido else 'No', compromiso.observaciones,
        ])
    for evidencia in informe['evidencias']:
        registro = (
            evidencia.atencion.titulo if evidencia.atencion_id
            else evidencia.compromiso.titulo
        )
        _agregar_fila(evidencias, [
            evidencia.identificador, evidencia.fecha_subida, registro,
            evidencia.get_estado_display(), evidencia.tipo_archivo,
            evidencia.subido_por.get_full_name() or evidencia.subido_por.get_username(),
            evidencia.validado_por.get_full_name() if evidencia.validado_por else '',
            evidencia.comentario_validacion or evidencia.descripcion,
        ])
    for carta in informe['cartas']:
        _agregar_fila(cartas, [
            carta.fecha_ingreso, carta.codigo, carta.asunto,
            carta.responsable.get_full_name() or carta.responsable.get_username(),
            str(carta.delegacion), carta.area_derivada, carta.get_estado_display(),
            carta.fecha_compromiso, carta.fecha_respuesta, carta.fecha_cierre,
        ])
    for gestion in informe['gestiones_sociales']:
        _agregar_fila(gestiones, [
            gestion.fecha_ingreso, gestion.codigo, gestion.titulo, str(gestion.vecino),
            gestion.responsable.get_full_name() or gestion.responsable.get_username(),
            str(gestion.delegacion), gestion.get_estado_display(), gestion.fecha_compromiso,
            gestion.fecha_cierre, gestion.dias_resolucion, gestion.resultado,
        ])
    for hito in informe['hitos']:
        delegacion_hito = (
            hito.actividad.delegacion if hito.actividad_id
            else hito.gestion_social.delegacion if hito.gestion_social_id
            else hito.compromiso.delegacion
        )
        _agregar_fila(hitos, [
            hito.fecha_programada, hito.codigo, hito.titulo,
            hito.responsable.get_full_name() or hito.responsable.get_username(),
            str(delegacion_hito), str(hito.territorio or ''),
            hito.get_periodicidad_display(), hito.get_estado_display(), hito.fecha_completada,
        ])
    for hoja in hojas:
        hoja.auto_filter.ref = f'A7:{hoja.cell(hoja.max_row, hoja.max_column).coordinate}'
        for celda in hoja[7]:
            celda.font = Font(bold=True)
        for columna in ('A', 'B', 'C'):
            hoja.column_dimensions[columna].width = 32
    buffer = BytesIO()
    libro.save(buffer)
    libro.close()
    respuesta = HttpResponse(buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="informe_sgr_periodo_{periodo.pk}.xlsx"'
    return respuesta
