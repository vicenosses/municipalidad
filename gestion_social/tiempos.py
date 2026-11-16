"""Cálculo de plazos entre los hitos registrados de una gestión social."""

from gestion_social.models import AccionGestionSocial


def _dias_entre(inicio, termino):
    if inicio is None or termino is None or termino < inicio:
        return None
    return (termino - inicio).days


def calcular_tiempos_gestion(gestion, acciones=None):
    if acciones is None:
        acciones = gestion.acciones_sociales.all()
    por_tipo = {}
    for accion in acciones:
        por_tipo.setdefault(accion.tipo, []).append(accion.fecha)

    primera_gestion = min(por_tipo.get(AccionGestionSocial.Tipo.ACCION, ()), default=None)
    visita = min(por_tipo.get(AccionGestionSocial.Tipo.VISITA, ()), default=None)
    informe = min(por_tipo.get(AccionGestionSocial.Tipo.INFORME, ()), default=None)
    beneficio = min(por_tipo.get(AccionGestionSocial.Tipo.BENEFICIO, ()), default=None)

    return {
        'ingreso_primera_gestion': _dias_entre(gestion.fecha_ingreso, primera_gestion),
        'programacion_visita': _dias_entre(gestion.fecha_visita_programada, visita),
        'visita_informe': _dias_entre(visita, informe),
        'atencion_beneficio': _dias_entre(gestion.fecha_atencion, beneficio),
    }
