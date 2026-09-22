from auditoria.models import RegistroAuditoria


def obtener_ip(request):
    if request is None:
        return None
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def registrar_auditoria(request, accion, instancia, descripcion):
    """Persiste un log de operación asociado al usuario autenticado."""
    usuario = getattr(request, 'user', None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    RegistroAuditoria.objects.create(
        usuario=usuario if usuario and usuario.is_authenticated else None,
        accion=accion,
        modelo=instancia._meta.label,
        objeto_id=str(instancia.pk),
        descripcion=descripcion,
        ip=obtener_ip(request),
    )
