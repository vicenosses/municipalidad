DELEGACION_SESION = 'delegacion_activa_id'


def delegaciones_autorizadas(user):
    from usuarios.models import Delegacion

    perfil = getattr(user, 'perfil', None)
    if user.is_superuser:
        return Delegacion.objects.filter(activa=True)
    if not perfil:
        return Delegacion.objects.none()
    ids = list(perfil.delegaciones.values_list('id', flat=True))
    if perfil.delegacion_id and perfil.delegacion_id not in ids:
        ids.append(perfil.delegacion_id)
    return Delegacion.objects.filter(id__in=ids, activa=True)


def get_delegacion_activa(request):
    """Delegación vigente en sesión o la del perfil."""
    if not request.user.is_authenticated:
        return None
    from usuarios.models import Delegacion

    autorizadas = delegaciones_autorizadas(request.user)
    if not autorizadas:
        perfil = getattr(request.user, 'perfil', None)
        return perfil.delegacion if perfil else None

    sid = request.session.get(DELEGACION_SESION)
    if sid:
        actual = autorizadas.filter(pk=sid).first()
        if actual:
            return actual
    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.delegacion_id:
        actual = autorizadas.filter(pk=perfil.delegacion_id).first()
        if actual:
            return actual
    return autorizadas.first()
