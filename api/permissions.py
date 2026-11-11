from rest_framework.permissions import BasePermission

from api.access import rol_usuario


class RolesPermitidos(BasePermission):
    message = 'Su rol no tiene permiso para esta operación.'

    def has_permission(self, request, view):
        permitidos = getattr(view, 'roles_por_accion', {}).get(getattr(view, 'action', None))
        return permitidos is None or rol_usuario(request.user) in permitidos


class EsAdministrador(BasePermission):
    message = 'Solo un administrador puede consultar este recurso.'

    def has_permission(self, request, view):
        return rol_usuario(request.user) == 'administrador'
