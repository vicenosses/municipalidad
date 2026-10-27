"""Ponderación Indicador → Meta sobre la única fuente métrica de 9F."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext

from sgr.calculos import ResultadoIndicador, calcular_resultado_indicador, calcular_resultados_indicadores
from sgr.models import Indicador

CERO = Decimal('0')
CIEN = Decimal('100')


@dataclass(frozen=True)
class ResultadoPonderado:
    indicador: Indicador
    metrica: ResultadoIndicador
    ponderacion: Decimal | None
    resultado_ponderado: Decimal | None
    estado: str


def ponderar_resultado(indicador, metrica):
    """No escribe ni consulta. Recibe el resultado 9F ya calculado."""
    peso = indicador.ponderacion
    valor = None
    if not indicador.activo:
        estado = 'inactivo'
    elif peso is None:
        estado = 'sin_ponderacion'
    elif not peso.is_finite() or peso <= CERO or peso > CIEN:
        estado = 'sin_participacion'
    elif metrica.cumplimiento.porcentaje is None:
        estado = metrica.cumplimiento.estado.value
    else:
        estado = 'calculado'
        with localcontext() as contexto:
            contexto.prec = 50
            valor = peso * metrica.cumplimiento.porcentaje / CIEN
    return ResultadoPonderado(indicador, metrica, peso, valor, estado)


def calcular_ponderacion_indicador(indicador):
    actual = Indicador.objects.get(pk=indicador.pk)
    return ponderar_resultado(actual, calcular_resultado_indicador(actual))


@dataclass(frozen=True)
class ResultadoMeta:
    indicadores: tuple[ResultadoPonderado, ...]
    ponderacion_asignada: Decimal
    ponderacion_pendiente: Decimal
    configuracion_completa: bool
    sin_ponderacion: int
    pesos_cero: int
    cobertura_calculable: Decimal
    resultado_ponderado_bruto: Decimal | None
    cumplimiento_normalizado: Decimal | None
    sin_resultado: int
    sin_limite: int


def calcular_resultado_meta(meta):
    """El llamador autoriza la Meta. Consultas constantes, incluso con tiempos."""
    return calcular_resultados_metas([meta])[meta.pk]


def calcular_resultados_metas(metas):
    """Agregación 9G en lote; el llamador autoriza todas las Metas recibidas."""
    grupos = {meta.pk: [] for meta in metas}
    if not grupos:
        return {}
    indicadores = list(Indicador.objects.filter(meta_id__in=grupos).select_related(
        'meta__periodo', 'meta__delegacion'))
    metricas = calcular_resultados_indicadores(indicadores)
    for indicador in indicadores:
        grupos[indicador.meta_id].append(ponderar_resultado(indicador, metricas[indicador.pk]))
    return {pk: _agregar_resultados(tuple(filas)) for pk, filas in grupos.items()}


def _agregar_resultados(filas):
    activos = [fila for fila in filas if fila.indicador.activo]
    asignado = sum((fila.ponderacion for fila in activos if fila.ponderacion is not None), CERO)
    sin_peso = sum(fila.ponderacion is None for fila in activos)
    ceros = sum(fila.ponderacion == CERO for fila in activos)
    calculables = [fila for fila in activos if fila.resultado_ponderado is not None]
    cobertura = sum((fila.ponderacion for fila in calculables), CERO)
    with localcontext() as contexto:
        contexto.prec = 50
        bruto = sum((fila.resultado_ponderado for fila in calculables), CERO) if calculables else None
        normalizado = (bruto / cobertura * CIEN).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP) if cobertura > CERO else None
    return ResultadoMeta(
        indicadores=filas, ponderacion_asignada=asignado, ponderacion_pendiente=CIEN - asignado,
        configuracion_completa=asignado == CIEN and sin_peso == 0 and ceros == 0,
        sin_ponderacion=sin_peso, pesos_cero=ceros, cobertura_calculable=cobertura,
        resultado_ponderado_bruto=bruto, cumplimiento_normalizado=normalizado,
        sin_resultado=sum(fila.metrica.cumplimiento.porcentaje is None for fila in activos),
        sin_limite=sum(fila.metrica.cumplimiento.estado == 'sin_limite' for fila in activos))
