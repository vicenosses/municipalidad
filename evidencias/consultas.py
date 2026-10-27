from evidencias.models import Evidencia


def evidencias_aprobadas_actividad(actividad_id):
    """Acepta un ID o una expresión ORM para consultas correlacionadas."""
    if actividad_id is None:
        return Evidencia.objects.none()
    return Evidencia.objects.filter(atencion_id=actividad_id, estado=Evidencia.Estado.APROBADA)


def tiene_evidencia_aprobada(actividad):
    return evidencias_aprobadas_actividad(actividad.pk).exists()
