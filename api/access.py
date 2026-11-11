from django.db.models import Q

from usuarios.mixins import obtener_rol
from usuarios.sesion import delegaciones_autorizadas


ROLES_VALIDOS = ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador')
ROLES_GESTORES = ('administrador', 'delegado', 'coordinador')


def rol_usuario(user):
    return obtener_rol(user)


def delegaciones_usuario(user):
    return delegaciones_autorizadas(user)


def en_delegacion(user, delegacion):
    return bool(delegacion and delegaciones_usuario(user).filter(pk=delegacion.pk).exists())


def filtrar_delegaciones(queryset, user, campo='delegacion'):
    if rol_usuario(user) == 'administrador':
        return queryset
    ids = delegaciones_usuario(user).values('pk')
    return queryset.filter(**{f'{campo}__in': ids})


def usuario_puede_ver_detalle(user, objeto):
    if rol_usuario(user) in (*ROLES_GESTORES, 'verificador'):
        return True
    return user.pk in {
        getattr(objeto, 'responsable_id', None),
        getattr(objeto, 'creado_por_id', None),
    }


def etiqueta_usuario(user):
    nombre = ' '.join((user.first_name or '').split())
    apellido = ' '.join((user.last_name or '').split())
    if nombre and apellido:
        return f'{nombre} {apellido[0]}.'
    return nombre or f'Usuario {user.pk}'


def rut_enmascarado(rut):
    if not rut:
        return ''
    return f'****{rut[-6:]}'


def filtro_hito_delegacion(user):
    if rol_usuario(user) == 'administrador':
        return Q()
    delegaciones = delegaciones_usuario(user).values('pk')
    return (
        Q(actividad__delegacion__in=delegaciones)
        | Q(gestion_social__delegacion__in=delegaciones)
        | Q(compromiso__delegacion__in=delegaciones)
    )
