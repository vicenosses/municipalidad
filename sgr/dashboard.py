"""Consultas y semáforo del inicio. Solo lectura; no registra auditoría.

El calendario incluye ambos extremos y el día de corte completo: un período
de diez días espera 50% al quinto día. No descuenta días no computables.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, Q
from django.utils import timezone

from sgr.models import Meta, Periodo
from sgr.permisos import ROLES_METAS
from sgr.ponderaciones import ResultadoMeta, calcular_resultados_metas
from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa, filtrar_contexto_territorial


@dataclass(frozen=True)
class Semaforo:
    estado: str
    texto: str


def calcular_avance_esperado(periodo, hoy):
    """Porcentaje calendario [0, 100]; None si las fechas son inválidas."""
    inicio, fin = periodo.fecha_inicio, periodo.fecha_fin
    if inicio is None or fin is None or fin < inicio:
        return None
    total = (fin - inicio).days + 1
    transcurrido = min(total, max(0, (hoy - inicio).days + 1))
    return Decimal(transcurrido) / Decimal(total) * Decimal('100')


def calcular_semaforo(real, esperado):
    if esperado is None or not esperado.is_finite() or esperado < 0:
        return Semaforo('sin_datos', 'Avance esperado no calculable')
    if esperado == 0:
        return Semaforo('sin_datos', 'Sin avance esperado positivo: período no iniciado')
    if real is None:
        return Semaforo('sin_datos', 'Sin cumplimiento numérico calculable')
    if not real.is_finite() or real < 0:
        return Semaforo('sin_datos', 'Cumplimiento no válido')
    if real >= esperado:
        return Semaforo('verde', 'Verde: al día o sobre lo esperado')
    if real >= esperado * Decimal('0.60'):
        return Semaforo('naranjo', 'Naranjo: entre el 60% y menos del 100% de lo esperado')
    return Semaforo('rojo', 'Rojo: menos del 60% de lo esperado')


def obtener_periodo_vigente(hoy):
    """No elige históricos, futuros ni uno arbitrario ante conflictos."""
    candidatos = list(Periodo.objects.filter(activo=True).filter(
        Q(fecha_inicio__lte=hoy, fecha_fin__gte=hoy)
        | Q(fecha_inicio__gt=F('fecha_fin'))
    )[:2])
    if not candidatos:
        return None, 'No hay un período activo vigente para la fecha de corte.'
    if len(candidatos) != 1 or candidatos[0].fecha_inicio > candidatos[0].fecha_fin:
        return None, 'Los períodos activos presentan fechas inválidas o superpuestas. Revise su configuración.'
    return candidatos[0], ''


@dataclass(frozen=True)
class FilaMeta:
    meta: Meta
    resultado: ResultadoMeta
    semaforo: Semaforo


def construir_dashboard(request, delegacion, hoy=None):
    hoy = hoy if hoy is not None else timezone.localdate()
    rol = obtener_rol(request.user)
    delegacion = get_delegacion_activa(request)
    contexto = {
        'fecha_corte': hoy,
        'contexto_territorial': 'Global: todas las delegaciones' if rol == 'administrador' and delegacion is None else delegacion,
        'puede_ver_detalle': rol in ROLES_METAS,
        'periodo': None, 'mensaje': '', 'esperado': None, 'filas': [],
        'total_metas': 0, 'metas_calculables': 0, 'metas_incompletas': 0,
        'conteos': dict(verde=0, naranjo=0, rojo=0, sin_datos=0),
    }
    if rol not in (*ROLES_METAS, 'funcionario', 'verificador'):
        contexto['mensaje'] = 'No tiene un rol habilitado para consultar el Dashboard SGR.'
        return contexto
    if rol != 'administrador' and delegacion is None:
        contexto['mensaje'] = 'No tiene una delegación autorizada activa. No se muestran datos territoriales.'
        return contexto
    periodo, mensaje = obtener_periodo_vigente(hoy)
    contexto.update(periodo=periodo, mensaje=mensaje)
    if periodo is None:
        return contexto
    metas = filtrar_contexto_territorial(Meta.objects.filter(
        periodo=periodo, activo=True).select_related('periodo', 'delegacion'), request)
    metas = list(metas)
    resultados = calcular_resultados_metas(metas)
    esperado = calcular_avance_esperado(periodo, hoy)
    contexto['esperado'] = esperado
    for meta in metas:
        resultado = resultados[meta.pk]
        semaforo = calcular_semaforo(resultado.cumplimiento_normalizado, esperado)
        contexto['filas'].append(FilaMeta(meta, resultado, semaforo))
        contexto['conteos'][semaforo.estado] += 1
        contexto['metas_calculables'] += resultado.cumplimiento_normalizado is not None
        contexto['metas_incompletas'] += not resultado.configuracion_completa
    contexto['total_metas'] = len(metas)
    return contexto
