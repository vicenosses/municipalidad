"""Cálculos derivados separados: avance operativo y resultado métrico oficial."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from enum import Enum

from django.db.models import Exists, OuterRef, Prefetch

from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from evidencias.consultas import evidencias_aprobadas_actividad, tiene_evidencia_aprobada
from sgr.models import AporteIndicador, Indicador
from sgr.tiempos import calcular_duracion_actividad

CERO = Decimal('0')
UNO = Decimal('1')


@dataclass(frozen=True)
class AvanceActividades:
    """Resumen binario; En proceso es un subconjunto de las no completas."""

    total_vinculaciones: int
    cantidad_consideradas: int
    excluidas_no_cumple: int
    excluidas_correccion: int
    cantidad_pendientes: int
    cantidad_cumple: int
    completas: int
    en_proceso: int
    sin_avance: int
    deshabilitadas: int
    consideradas_deshabilitadas: int
    puntos_ponderados: Decimal  # Nombre conservado por compatibilidad; suma solo 0/1.
    porcentaje_avance: Decimal | None

    @property
    def hay_base_calculable(self):
        return self.cantidad_consideradas > 0

    @property
    def cantidad_excluidas(self):
        return self.excluidas_no_cumple + self.excluidas_correccion

    @property
    def no_completas(self):
        return self.cantidad_consideradas - self.completas


def calcular_avance_actividad(actividad, *, evidencia_aprobada=None):
    """Valor binario: solo Cerrada con evidencia aprobada aporta uno.

    El cálculo de Indicador suministra la existencia de evidencia mediante una
    anotación SQL, evitando consultas adicionales por cada Actividad.
    """
    if actividad.estado == AtencionCiudadana.Estado.CERRADA:
        if evidencia_aprobada is None:
            evidencia_aprobada = tiene_evidencia_aprobada(actividad)
        return UNO if evidencia_aprobada else CERO
    return CERO


def calcular_avance_indicador(indicador):
    """Calcula sobre vinculaciones actuales de un Indicador ya autorizado.

    No filtra por activo: deshabilitar una Actividad no cancela su asociación
    ni constituye un estado de avance. No se generan escrituras ni auditoría.
    """
    aportes = AporteIndicador.objects.filter(indicador=indicador).select_related('actividad').annotate(
        evidencia_aprobada=Exists(evidencias_aprobadas_actividad(OuterRef('actividad_id'))),
    ).order_by()
    cantidades = dict(total_vinculaciones=0, cantidad_consideradas=0, excluidas_no_cumple=0,
                      excluidas_correccion=0, cantidad_pendientes=0, cantidad_cumple=0,
                      completas=0, en_proceso=0, sin_avance=0, deshabilitadas=0,
                      consideradas_deshabilitadas=0)
    puntos = CERO
    for aporte in aportes:
        cantidades['total_vinculaciones'] += 1
        if not aporte.actividad.activo:
            cantidades['deshabilitadas'] += 1
        if aporte.estado == AporteIndicador.Estado.NO_CUMPLE:
            cantidades['excluidas_no_cumple'] += 1
            continue
        if aporte.estado == AporteIndicador.Estado.REQUIERE_CORRECCION:
            cantidades['excluidas_correccion'] += 1
            continue
        cantidades['cantidad_consideradas'] += 1
        if not aporte.actividad.activo:
            cantidades['consideradas_deshabilitadas'] += 1
        if aporte.estado == AporteIndicador.Estado.PENDIENTE:
            cantidades['cantidad_pendientes'] += 1
        elif aporte.estado == AporteIndicador.Estado.CUMPLE:
            cantidades['cantidad_cumple'] += 1
        puntaje = calcular_avance_actividad(aporte.actividad, evidencia_aprobada=aporte.evidencia_aprobada)
        puntos += puntaje
        if aporte.actividad.estado == AtencionCiudadana.Estado.EN_PROCESO:
            cantidades['en_proceso'] += 1
        categoria = 'completas' if puntaje == UNO else 'sin_avance'
        cantidades[categoria] += 1
    consideradas = cantidades['cantidad_consideradas']
    porcentaje = ((puntos / Decimal(consideradas)) * Decimal('100')).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    ) if consideradas else None
    return AvanceActividades(**cantidades, puntos_ponderados=puntos, porcentaje_avance=porcentaje)


class EstadoCumplimiento(str, Enum):
    CALCULADO = 'calculado'
    SIN_RESULTADO = 'sin_resultado'
    OBJETIVO_INVALIDO = 'objetivo_invalido'
    SIN_LIMITE = 'sin_limite'
    DATOS_INVALIDOS = 'datos_invalidos'


@dataclass(frozen=True)
class CumplimientoIndicador:
    porcentaje: Decimal | None
    estado: EstadoCumplimiento


def calcular_cumplimiento(resultado, objetivo, sentido):
    if resultado is None:
        return CumplimientoIndicador(None, EstadoCumplimiento.SIN_RESULTADO)
    if not objetivo.is_finite() or objetivo <= CERO:
        return CumplimientoIndicador(None, EstadoCumplimiento.OBJETIVO_INVALIDO)
    if not resultado.is_finite() or resultado < CERO:
        return CumplimientoIndicador(None, EstadoCumplimiento.DATOS_INVALIDOS)
    if sentido == Indicador.Sentido.MENOR and resultado == CERO:
        return CumplimientoIndicador(None, EstadoCumplimiento.SIN_LIMITE)
    with localcontext() as contexto:
        contexto.prec = 50
        if sentido == Indicador.Sentido.MAYOR:
            porcentaje = resultado / objetivo * Decimal('100')
        elif sentido == Indicador.Sentido.MENOR:
            porcentaje = objetivo / resultado * Decimal('100')
        else:
            return CumplimientoIndicador(None, EstadoCumplimiento.DATOS_INVALIDOS)
        return CumplimientoIndicador(porcentaje.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
                                      EstadoCumplimiento.CALCULADO)


@dataclass(frozen=True)
class ResultadoIndicador:
    unidad: str
    unidad_presentacion: str
    sentido: str
    objetivo: Decimal
    resultado: Decimal | None
    cumplimiento: CumplimientoIndicador
    total_aportes: int
    cantidad_cumple: int
    cantidad_no_cumple: int
    cantidad_pendiente: int
    cantidad_correccion: int
    base_utilizada: int
    sin_valor_validado: int
    sin_duracion_calculable: int
    observaciones: tuple[str, ...]

    @property
    def tiene_resultado(self):
        return self.resultado is not None

    @property
    def objetivo_valido(self):
        return self.objetivo.is_finite() and self.objetivo > CERO

    @property
    def es_temporal(self):
        return self.unidad in (Indicador.Unidad.HORAS, Indicador.Unidad.DIAS)


def calcular_resultado_indicador(indicador):
    """Lee objetivo y datos vigentes; el llamador debe autorizar el Indicador."""
    actual = Indicador.objects.get(pk=indicador.pk)
    temporal = actual.unidad_medida in (Indicador.Unidad.HORAS, Indicador.Unidad.DIAS)
    return _calcular_resultado_desde_aportes(actual, list(_aportes_para_metricas([actual.pk], temporal)))


def _aportes_para_metricas(ids, temporal):
    consulta = AporteIndicador.objects.filter(indicador_id__in=ids).order_by()
    if temporal:
        consulta = consulta.select_related('actividad').prefetch_related(Prefetch(
            'actividad__historial_estados',
            queryset=HistorialEstadoActividad.objects.order_by('pk'), to_attr='historial_para_metrica',
        ))
    return consulta


def calcular_resultados_indicadores(indicadores):
    """Mismas reglas 9F, en lote sobre instancias vigentes ya autorizadas."""
    indicadores = list(indicadores)
    grupos = {indicador.pk: [] for indicador in indicadores}
    temporal = any(indicador.unidad_medida in (Indicador.Unidad.HORAS, Indicador.Unidad.DIAS)
                   for indicador in indicadores)
    if grupos:
        for aporte in _aportes_para_metricas(list(grupos), temporal):
            grupos[aporte.indicador_id].append(aporte)
    return {indicador.pk: _calcular_resultado_desde_aportes(indicador, grupos[indicador.pk])
            for indicador in indicadores}


def _calcular_resultado_desde_aportes(actual, aportes):
    temporal = actual.unidad_medida in (Indicador.Unidad.HORAS, Indicador.Unidad.DIAS)
    cumple = [aporte for aporte in aportes if aporte.estado == AporteIndicador.Estado.CUMPLE]
    no_cumple = sum(aporte.estado == AporteIndicador.Estado.NO_CUMPLE for aporte in aportes)
    pendientes = sum(aporte.estado == AporteIndicador.Estado.PENDIENTE for aporte in aportes)
    correcciones = sum(aporte.estado == AporteIndicador.Estado.REQUIERE_CORRECCION for aporte in aportes)
    base = 0
    sin_valor = 0
    sin_tiempo = 0
    observaciones = []
    unidad = actual.unidad_medida
    if unidad == Indicador.Unidad.CANTIDAD:
        resultado = Decimal(len(cumple))
        base = len(cumple)
    elif unidad == Indicador.Unidad.PORCENTAJE:
        base = len(cumple) + no_cumple
        resultado = Decimal(len(cumple)) / Decimal(base) * Decimal('100') if base else None
    elif unidad == Indicador.Unidad.OTRA:
        valores = [aporte.valor_validado for aporte in cumple if aporte.valor_validado is not None]
        sin_valor = len(cumple) - len(valores)
        base = len(valores)
        resultado = sum(valores, CERO) if valores or not cumple else None
        if sin_valor:
            observaciones.append(f'{sin_valor} aportes Cumple sin valor validado, excluidos de la suma.')
    elif temporal:
        valores = []
        motivos = {}
        for aporte in cumple:
            duracion = calcular_duracion_actividad(
                aporte.actividad, aporte.actividad.historial_para_metrica,
                dias_habiles=unidad == Indicador.Unidad.DIAS,
            )
            if duracion.valor is None:
                sin_tiempo += 1
                motivos[duracion.motivo_no_calculable] = motivos.get(duracion.motivo_no_calculable, 0) + 1
            else:
                valores.append(duracion.valor)
        base = len(valores)
        resultado = sum(valores, CERO) / Decimal(base) if base else None
        etiquetas = {'sin_historial': 'sin historial temporal',
                     'historial_incompleto': 'con ciclos incompletos o historia previa insuficiente',
                     'historial_inconsistente': 'con historial temporal inconsistente'}
        for motivo, cantidad in motivos.items():
            observaciones.append(f'{cantidad} Actividades Cumple {etiquetas[motivo]}, excluidas del promedio.')
    else:
        resultado = None
        observaciones.append('Unidad de medida no reconocida.')
    etiqueta = {
        Indicador.Unidad.CANTIDAD: '', Indicador.Unidad.PORCENTAJE: '%',
        Indicador.Unidad.HORAS: 'h', Indicador.Unidad.DIAS: 'días hábiles',
        Indicador.Unidad.OTRA: actual.unidad_personalizada,
    }.get(unidad, '')
    return ResultadoIndicador(
        unidad=unidad, unidad_presentacion=etiqueta, sentido=actual.get_sentido_display(),
        objetivo=actual.valor_objetivo, resultado=resultado,
        cumplimiento=calcular_cumplimiento(resultado, actual.valor_objetivo, actual.sentido),
        total_aportes=len(aportes), cantidad_cumple=len(cumple), cantidad_no_cumple=no_cumple,
        cantidad_pendiente=pendientes, cantidad_correccion=correcciones, base_utilizada=base,
        sin_valor_validado=sin_valor, sin_duracion_calculable=sin_tiempo, observaciones=tuple(observaciones),
    )
