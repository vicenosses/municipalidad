"""Informes de solo lectura sobre los resultados vigentes de 9F, 9G y 10A."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.models import Prefetch
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from cartas.models import Carta
from evidencias.models import Evidencia
from gestion_social.models import GestionSocial
from hitos.models import Hito
from sgr.dashboard import FilaMeta, calcular_avance_esperado, calcular_semaforo, obtener_periodo_vigente
from sgr.asignaciones import calcular_resultado_asignacion
from sgr.models import AporteIndicador, AsignacionMeta, Meta
from sgr.permisos import ROLES_INFORMES, ROLES_METAS
from sgr.ponderaciones import calcular_resultados_metas
from usuarios.mixins import obtener_rol
from usuarios.sesion import delegaciones_autorizadas, get_delegacion_activa


def autorizar_informe(request, delegacion_seleccionada=None):
    rol = obtener_rol(request.user)
    if rol not in ROLES_INFORMES:
        raise PermissionDenied('No tiene un rol habilitado para consultar informes SGR.')
    delegacion = get_delegacion_activa(request)
    if delegacion_seleccionada is not None:
        if not delegaciones_autorizadas(request.user).filter(pk=delegacion_seleccionada.pk).exists():
            raise PermissionDenied('La delegación seleccionada está fuera de su alcance autorizado.')
        if rol != 'administrador' and delegacion_seleccionada != delegacion:
            raise PermissionDenied('No puede consultar otra delegación.')
        if rol == 'administrador' and delegacion and delegacion_seleccionada != delegacion:
            raise PermissionDenied('La delegación seleccionada no coincide con el contexto activo.')
        delegacion = delegacion_seleccionada
    if rol == 'administrador':
        return delegacion
    if delegacion is None:
        raise PermissionDenied('No tiene una delegación activa autorizada para consultar informes SGR.')
    return delegacion


def construir_informe(
    request, periodo=None, hoy=None, delegacion=None, funcionario=None, meta=None,
):
    """El período explícito puede ser histórico; no reconstruye estados pasados.

    El alcance siempre se obtiene de la sesión autorizada, nunca de parámetros
    territoriales de la URL. También se autoriza al invocar el servicio solo.
    """
    delegacion = autorizar_informe(request, delegacion)
    hoy = hoy if hoy is not None else timezone.localdate()
    contexto = {
        'periodo': periodo, 'fecha_corte': hoy, 'esperado': None, 'mensaje': '',
        'contexto_territorial': delegacion if delegacion else 'Global: todas las delegaciones',
        'puede_ver_detalle': obtener_rol(request.user) in ROLES_METAS,
        'filas': [], 'total_metas': 0, 'total_indicadores': 0, 'indicadores_activos': 0,
        'metas_calculables': 0, 'metas_incompletas': 0, 'funcionario': funcionario,
        'meta_seleccionada': meta, 'asignaciones': [], 'actividades': [],
        'compromisos': [], 'evidencias': [], 'cartas': [],
        'gestiones_sociales': [], 'hitos': [],
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
    if meta is not None:
        metas = metas.filter(pk=meta.pk)
    metas = list(metas)
    resultados = calcular_resultados_metas(metas)
    for meta_actual in metas:
        resultado = resultados[meta_actual.pk]
        contexto['filas'].append(FilaMeta(meta_actual, resultado,
            calcular_semaforo(resultado.cumplimiento_normalizado, esperado)))
        contexto['total_indicadores'] += len(resultado.indicadores)
        contexto['indicadores_activos'] += sum(f.indicador.activo for f in resultado.indicadores)
        contexto['metas_calculables'] += resultado.cumplimiento_normalizado is not None
        contexto['metas_incompletas'] += not resultado.configuracion_completa
    contexto['total_metas'] = len(metas)

    asignaciones = AsignacionMeta.objects.filter(
        meta__periodo=periodo, meta__activo=True, activa=True,
    ).select_related('meta__periodo', 'meta__delegacion', 'funcionario')
    if delegacion is not None:
        asignaciones = asignaciones.filter(meta__delegacion=delegacion)
    if funcionario is not None:
        asignaciones = asignaciones.filter(funcionario=funcionario)
    if meta is not None:
        asignaciones = asignaciones.filter(meta=meta)
    contexto['asignaciones'] = [
        calcular_resultado_asignacion(asignacion) for asignacion in asignaciones
    ]

    actividades = AtencionCiudadana.objects.filter(
        fecha__range=(periodo.fecha_inicio, periodo.fecha_fin),
    ).select_related(
        'responsable', 'delegacion', 'tipo', 'subatencion',
    ).prefetch_related(
        'evidencias',
        Prefetch(
            'aporte_indicador',
            queryset=AporteIndicador.objects.select_related('indicador__meta'),
        ),
    )
    if delegacion is not None:
        actividades = actividades.filter(delegacion=delegacion)
    if funcionario is not None:
        actividades = actividades.filter(responsable=funcionario)
    if meta is not None:
        actividades = actividades.filter(aporte_indicador__indicador__meta=meta)
    contexto['actividades'] = list(actividades.order_by('fecha', 'pk'))

    compromisos = Compromiso.objects.filter(
        fecha_hora__date__range=(periodo.fecha_inicio, periodo.fecha_fin),
    ).select_related('responsable', 'delegacion').prefetch_related('actividades')
    if delegacion is not None:
        compromisos = compromisos.filter(delegacion=delegacion)
    if funcionario is not None:
        compromisos = compromisos.filter(responsable=funcionario)
    if meta is not None:
        compromisos = compromisos.filter(actividades__aporte_indicador__indicador__meta=meta)
    contexto['compromisos'] = list(compromisos.distinct().order_by('fecha_hora', 'pk'))

    evidencias = Evidencia.objects.filter(
        Q(atencion__in=contexto['actividades'])
        | Q(compromiso__in=contexto['compromisos'])
    ).select_related('subido_por', 'validado_por', 'atencion', 'compromiso')
    contexto['evidencias'] = list(evidencias.order_by('-fecha_subida', '-pk'))

    cartas = Carta.objects.filter(
        fecha_ingreso__range=(periodo.fecha_inicio, periodo.fecha_fin), activo=True,
    ).select_related('delegacion', 'territorio', 'responsable')
    gestiones = GestionSocial.objects.filter(
        fecha_ingreso__range=(periodo.fecha_inicio, periodo.fecha_fin), activo=True,
    ).select_related('delegacion', 'territorio', 'responsable', 'vecino', 'asignacion_meta')
    hitos = Hito.objects.filter(
        fecha_programada__range=(periodo.fecha_inicio, periodo.fecha_fin), activo=True,
    ).select_related(
        'responsable', 'actividad__delegacion', 'gestion_social__delegacion',
        'compromiso__delegacion', 'asignacion_meta__meta', 'territorio',
    ).prefetch_related('actividades')
    if delegacion is not None:
        cartas = cartas.filter(delegacion=delegacion)
        gestiones = gestiones.filter(delegacion=delegacion)
        hitos = hitos.filter(
            Q(actividad__delegacion=delegacion)
            | Q(gestion_social__delegacion=delegacion)
            | Q(compromiso__delegacion=delegacion)
        )
    if funcionario is not None:
        cartas = cartas.filter(responsable=funcionario)
        gestiones = gestiones.filter(responsable=funcionario)
        hitos = hitos.filter(responsable=funcionario)
    if meta is not None:
        cartas = cartas.none()
        gestiones = gestiones.filter(asignacion_meta__meta=meta)
        hitos = hitos.filter(
            Q(asignacion_meta__meta=meta)
            | Q(actividades__aporte_indicador__indicador__meta=meta)
        ).distinct()
    contexto['cartas'] = list(cartas.order_by('fecha_ingreso', 'pk'))
    contexto['gestiones_sociales'] = list(gestiones.order_by('fecha_ingreso', 'pk'))
    for gestion in contexto['gestiones_sociales']:
        cierre = gestion.fecha_cierre or hoy
        gestion.dias_resolucion = max((cierre - gestion.fecha_ingreso).days, 0)
    contexto['hitos'] = list(hitos.order_by('fecha_programada', 'pk'))
    return contexto
