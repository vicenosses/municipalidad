DELEGACION_SESION = 'delegacion_activa_id'
CONTEXTO_GLOBAL = 'global'
ROLES_TERRITORIALES = ('delegado', 'coordinador', 'funcionario', 'verificador')


def delegaciones_autorizadas(user):
    from usuarios.mixins import obtener_rol
    from usuarios.models import Delegacion

    if not user.is_authenticated:
        return Delegacion.objects.none()
    rol = obtener_rol(user)
    if rol == 'administrador':
        return Delegacion.objects.filter(activa=True)

    perfil = getattr(user, 'perfil', None)
    if not perfil or rol not in ROLES_TERRITORIALES:
        return Delegacion.objects.none()
    return Delegacion.objects.filter(
        id__in=perfil.delegaciones.values('id'),
        activa=True,
    )


def usuario_tiene_alcance_delegacion(user, delegacion):
    if not delegacion or not user.is_authenticated:
        return False
    return delegaciones_autorizadas(user).filter(pk=delegacion.pk).exists()


def get_delegacion_activa(request):
    """Cache administrativo por solicitud; autorizaciones territoriales siempre vigentes."""
    from usuarios.mixins import obtener_rol

    if not request.user.is_authenticated:
        return None
    if obtener_rol(request.user) != 'administrador':
        return _resolver_delegacion_activa(request)
    clave = (request.user.pk, obtener_rol(request.user), repr(request.session.get(DELEGACION_SESION)))
    cache = getattr(request, '_contexto_territorial_cache', None)
    if cache is not None and cache[0] == clave:
        return cache[1]
    delegacion = _resolver_delegacion_activa(request)
    clave = (request.user.pk, obtener_rol(request.user), repr(request.session.get(DELEGACION_SESION)))
    request._contexto_territorial_cache = (clave, delegacion)
    return delegacion


def _resolver_delegacion_activa(request):
    """Administrador: selección explícita o global (None), sin primera arbitraria.

    Los territoriales conservan la validación de sus autorizaciones. Un contexto
    obsoleto del administrador se recupera como global, dentro de sus permisos.
    """
    from usuarios.mixins import obtener_rol

    if not request.user.is_authenticated:
        return None

    autorizadas = delegaciones_autorizadas(request.user)
    sid = request.session.get(DELEGACION_SESION)
    administrador = obtener_rol(request.user) == 'administrador'
    if administrador and sid in (None, CONTEXTO_GLOBAL):
        return None
    if sid is not None:
        try:
            if isinstance(sid, bool) or not isinstance(sid, (int, str)):
                raise ValueError
            sid = int(sid)
        except (TypeError, ValueError):
            sid = None
        actual = autorizadas.filter(pk=sid).first() if sid is not None else None
        if actual:
            return actual
        request.session.pop(DELEGACION_SESION, None)
        if administrador:
            request.contexto_territorial_recuperado = True
            return None

    if administrador:
        return None

    perfil = getattr(request.user, 'perfil', None)
    if perfil and perfil.delegacion_id:
        actual = autorizadas.filter(pk=perfil.delegacion_id).first()
        if actual:
            return actual
    return autorizadas.first()


def en_contexto_delegacion(request, delegacion):
    """Valida el contexto de un objeto también al escribir por ID directo."""
    from usuarios.mixins import obtener_rol

    rol = obtener_rol(request.user)
    if rol not in ('administrador', *ROLES_TERRITORIALES):
        return False
    activa = get_delegacion_activa(request)
    return (rol == 'administrador' and activa is None) or (
        activa is not None and delegacion is not None and activa.pk == delegacion.pk
    )


def filtrar_contexto_territorial(queryset, request, campo='delegacion'):
    """Global solo para administrador; un territorial sin alcance recibe vacío."""
    from usuarios.mixins import obtener_rol

    rol = obtener_rol(request.user)
    if rol not in ('administrador', *ROLES_TERRITORIALES):
        return queryset.none()
    delegacion = get_delegacion_activa(request)
    if rol == 'administrador' and delegacion is None:
        return queryset
    return queryset.filter(**{campo: delegacion}) if delegacion else queryset.none()
