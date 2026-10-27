"""Informes de solo lectura sobre los resultados vigentes de 9F, 9G y 10A."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from sgr.dashboard import FilaMeta, calcular_avance_esperado, calcular_semaforo, obtener_periodo_vigente
from sgr.models import Meta
from sgr.permisos import ROLES_INFORMES, ROLES_METAS
from sgr.ponderaciones import calcular_resultados_metas
from usuarios.mixins import obtener_rol
from usuarios.sesion import get_delegacion_activa


def autorizar_informe(request):
    rol = obtener_rol(request.user)
    if rol not in ROLES_INFORMES:
        raise PermissionDenied('No tiene un rol habilitado para consultar informes SGR.')
    if rol == 'administrador':
        return get_delegacion_activa(request)
    delegacion = get_delegacion_activa(request)
    if delegacion is None:
        raise PermissionDenied('No tiene una delegación activa autorizada para consultar informes SGR.')
    return delegacion


def construir_informe(request, periodo=None, hoy=None):
    """El período explícito puede ser histórico; no reconstruye estados pasados.

    El alcance siempre se obtiene de la sesión autorizada, nunca de parámetros
    territoriales de la URL. También se autoriza al invocar el servicio solo.
    """
    delegacion = autorizar_informe(request)
    hoy = hoy if hoy is not None else timezone.localdate()
    contexto = {
        'periodo': periodo, 'fecha_corte': hoy, 'esperado': None, 'mensaje': '',
        'contexto_territorial': delegacion if delegacion else 'Global: todas las delegaciones',
        'puede_ver_detalle': obtener_rol(request.user) in ROLES_METAS,
        'filas': [], 'total_metas': 0, 'total_indicadores': 0, 'indicadores_activos': 0,
        'metas_calculables': 0, 'metas_incompletas': 0,
    }
    if periodo is None:
        periodo, contexto['mensaje'] = obtener_periodo_vigente(hoy)
        contexto['periodo'] = periodo
    if periodo is None:
        return contexto
    esperado = calcular_avance_esperado(periodo, hoy)
    if esperado is None:
        contexto['mensaje'] = 'El período seleccionado tiene fechas inválidas. No se muestran resultados.'
        return contexto
    contexto['esperado'] = esperado
    metas = Meta.objects.filter(periodo=periodo, activo=True).select_related('periodo', 'delegacion')
    if delegacion is not None:
        metas = metas.filter(delegacion=delegacion)
    metas = list(metas)
    resultados = calcular_resultados_metas(metas)
    for meta in metas:
        resultado = resultados[meta.pk]
        contexto['filas'].append(FilaMeta(meta, resultado,
            calcular_semaforo(resultado.cumplimiento_normalizado, esperado)))
        contexto['total_indicadores'] += len(resultado.indicadores)
        contexto['indicadores_activos'] += sum(f.indicador.activo for f in resultado.indicadores)
        contexto['metas_calculables'] += resultado.cumplimiento_normalizado is not None
        contexto['metas_incompletas'] += not resultado.configuracion_completa
    contexto['total_metas'] = len(metas)
    return contexto
