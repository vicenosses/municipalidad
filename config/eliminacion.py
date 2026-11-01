from django.apps import apps
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from auditoria.utils import registrar_auditoria
from usuarios.mixins import RolRequiredMixin


MODELOS = {
    'usuario': ('auth', 'User'), 'delegacion': ('usuarios', 'Delegacion'),
    'rol': ('usuarios', 'Rol'), 'cargo': ('usuarios', 'Cargo'),
    'tipo': ('catalogos', 'TipoAtencion'), 'sub': ('catalogos', 'SubAtencion'),
    'item': ('catalogos', 'ItemMeta'), 'actividad': ('atenciones', 'AtencionCiudadana'),
    'periodo': ('sgr', 'Periodo'), 'meta': ('sgr', 'Meta'), 'indicador': ('sgr', 'Indicador'),
}


def relaciones_existentes(obj):
    relaciones = set()
    for campo in obj._meta.get_fields():
        if not (campo.auto_created and not campo.concrete and (campo.one_to_many or campo.one_to_one or campo.many_to_many)):
            continue
        accessor = campo.get_accessor_name()
        if not accessor or (obj._meta.label_lower == 'auth.user' and accessor == 'perfil'):
            continue
        if obj._meta.label_lower == 'atenciones.atencionciudadana' and campo.related_model._meta.model_name == 'historialestadoactividad':
            continue
        try:
            valor = getattr(obj, accessor)
            existe = valor.exists() if hasattr(valor, 'exists') else valor is not None
        except ObjectDoesNotExist:
            existe = False
        if existe:
            relaciones.add(str(campo.related_model._meta.verbose_name_plural))
    if obj._meta.label_lower == 'usuarios.cargo':
        Perfil = apps.get_model('usuarios', 'Perfil')
        if Perfil.objects.filter(cargo=obj.nombre).exists():
            relaciones.add('usuarios con este cargo')
    return sorted(relaciones)


class EliminarRegistroView(RolRequiredMixin, View):
    roles_permitidos = ('administrador',)

    def post(self, request, tipo, pk):
        if tipo not in MODELOS:
            raise Http404
        modelo = apps.get_model(*MODELOS[tipo])
        destino = request.POST.get('next', '/')
        if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            destino = '/'
        try:
            with transaction.atomic():
                qs = modelo.objects.select_for_update()
                if tipo == 'actividad':
                    from atenciones.permisos import queryset_atenciones
                    qs = queryset_atenciones(request).select_for_update()
                elif tipo in ('tipo', 'sub'):
                    from catalogos.permisos import catalogos_editables
                    qs = catalogos_editables(qs, request)
                elif tipo == 'usuario':
                    from usuarios.views import perfiles_en_contexto
                    qs = qs.filter(pk__in=perfiles_en_contexto(request).values('usuario_id'))
                elif tipo in ('meta', 'indicador'):
                    from sgr.permisos import metas_visibles, indicadores_visibles
                    qs = (metas_visibles(request) if tipo == 'meta' else indicadores_visibles(request)).select_for_update()
                obj = get_object_or_404(qs, pk=pk)
                if isinstance(obj, User) and obj.pk == request.user.pk:
                    messages.error(request, 'No puedes eliminar tu propia cuenta.')
                    return redirect(destino)
                relaciones = relaciones_existentes(obj)
                if relaciones:
                    messages.error(request, 'No se puede eliminar: tiene registros relacionados (%s).' % ', '.join(relaciones))
                    return redirect(destino)
                registrar_auditoria(request, 'eliminar', obj, f'Eliminación permanente de {obj}')
                if tipo == 'actividad':
                    obj.historial_estados.all().delete()
                obj.delete()
        except (ProtectedError, RestrictedError):
            messages.error(request, 'No se puede eliminar porque existen registros relacionados.')
            return redirect(destino)
        messages.success(request, 'Registro eliminado permanentemente.')
        return redirect(destino)
