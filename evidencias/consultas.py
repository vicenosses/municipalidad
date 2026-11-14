from evidencias.models import Evidencia


def evidencias_vigentes_actividad(actividad_id):
    """Evidencias actuales, excluyendo las que ya fueron reemplazadas."""
    if actividad_id is None:
        return Evidencia.objects.none()
    reemplazadas = Evidencia.objects.filter(
        atencion_id=actividad_id,
        reemplaza__isnull=False,
    ).values_list('reemplaza_id', flat=True)
    return Evidencia.objects.filter(atencion_id=actividad_id).exclude(pk__in=reemplazadas)


def evidencias_aprobadas_actividad(actividad_id):
    """Acepta un ID o una expresión ORM para consultas correlacionadas."""
    if actividad_id is None:
        return Evidencia.objects.none()
    return Evidencia.objects.filter(atencion_id=actividad_id, estado=Evidencia.Estado.APROBADA)


def tiene_evidencia_aprobada(actividad):
    return puede_cerrar_actividad_por_evidencias(actividad.pk)


def puede_cerrar_actividad_por_evidencias(actividad_id):
    vigentes = evidencias_vigentes_actividad(actividad_id)
    return (
        vigentes.filter(estado=Evidencia.Estado.APROBADA).exists()
        and not vigentes.filter(estado=Evidencia.Estado.RECHAZADA).exists()
        and not vigentes.filter(
            reemplaza__isnull=False,
            estado=Evidencia.Estado.PENDIENTE,
        ).exists()
    )
