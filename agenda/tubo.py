"""Vista compartida del tubo sin duplicar actividades y compromisos."""
from django import forms
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from agenda.models import Compromiso
from agenda.views import ROLES_AGENDA, ROLES_GESTORES, normalizar_busqueda
from atenciones.models import AtencionCiudadana
from gestion_social.models import GestionSocial
from usuarios.mixins import RolRequiredMixin, obtener_rol
from usuarios.models import Perfil
from usuarios.sesion import filtrar_contexto_territorial


class FiltroTuboForm(forms.Form):
    q = forms.CharField(label='Buscar', required=False, max_length=100,
        widget=forms.TextInput(attrs={'class':'form-control', 'placeholder':'Código, nombre o RUT', 'autocomplete':'off'}))
    tipo = forms.ChoiceField(label='Tipo', required=False, choices=(('', 'Todos'), ('actividad', 'Actividad'), ('gestion_social', 'Gestión social')), widget=forms.Select(attrs={'class':'form-select'}))
    estado = forms.ChoiceField(label='Estado', required=False, choices=(('', 'Todos'), ('pendiente', 'Pendiente'), ('en_proceso', 'En proceso'), ('cerrado', 'Cerrado'), ('vencido', 'Vencido')), widget=forms.Select(attrs={'class':'form-select'}))
    responsable = forms.ModelChoiceField(label='Responsable', required=False, queryset=Perfil.objects.none(), widget=forms.Select(attrs={'class':'form-select'}))
    desde = forms.DateField(label='Desde', required=False, widget=forms.DateInput(attrs={'class':'form-control', 'type':'date'}))
    hasta = forms.DateField(label='Hasta', required=False, widget=forms.DateInput(attrs={'class':'form-control', 'type':'date'}))

    def __init__(self, *args, responsables, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsable'].queryset = responsables.select_related('usuario').order_by('usuario__username')
        self.fields['responsable'].label_from_instance = lambda perfil: perfil.usuario.get_full_name() or perfil.usuario.username

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            self.add_error('hasta', 'La fecha final debe ser igual o posterior a la inicial.')
        return datos


def _normalizar_rut(valor):
    return ''.join(c for c in normalizar_busqueda(valor) if c.isalnum())


def _actividad_fila(actividad):
    compromisos = list(actividad.compromisos.all())
    pendientes = [c for c in compromisos if c.estado != Compromiso.Estado.REALIZADO]
    seleccion = min(pendientes or compromisos, key=lambda c: c.fecha_hora) if compromisos else None
    return {'tipo': 'actividad', 'tipo_texto': 'Actividad', 'codigo': f'ACT-{actividad.pk:06d}',
        'titulo': actividad.titulo, 'solicitante': actividad.solicitante,
        'rut': seleccion.rut_solicitante if seleccion else '', 'fecha': actividad.fecha,
        'plazo': timezone.localtime(seleccion.fecha_hora).date() if seleccion else None,
        'estado': actividad.estado, 'estado_texto': actividad.get_estado_display(),
        'cerrado': actividad.estado == AtencionCiudadana.Estado.CERRADA,
        'responsable': actividad.responsable, 'delegacion': actividad.delegacion,
        'url': reverse('atenciones:detalle', args=[actividad.pk])}


def _gestion_fila(gestion, user, rol):
    autorizada = rol in ROLES_GESTORES or user.pk in (gestion.responsable_id, gestion.creado_por_id)
    vecino = gestion.vecino if autorizada else None
    return {'tipo': 'gestion_social', 'tipo_texto': 'Gestión social', 'codigo': gestion.codigo,
        'titulo': gestion.titulo if autorizada else 'Gestión social',
        'solicitante': str(vecino) if vecino else '', 'rut': vecino.rut if vecino else '',
        'fecha': gestion.fecha_ingreso, 'plazo': gestion.fecha_compromiso,
        'estado': gestion.estado, 'estado_texto': gestion.get_estado_display(),
        'cerrado': gestion.estado == GestionSocial.Estado.CERRADA,
        'responsable': gestion.responsable, 'delegacion': gestion.delegacion,
        'url': reverse('atenciones:gestion_social:detalle', args=[gestion.pk]) if autorizada else None}


def _estado_coincide(fila, estado, hoy):
    if not estado:
        return True
    if estado == 'vencido':
        return bool(fila['plazo'] and fila['plazo'] < hoy and not fila['cerrado'])
    if estado == 'cerrado':
        return fila['cerrado']
    if estado == 'pendiente':
        return fila['estado'] in ('registrada', 'pendiente', 'pendiente_antecedentes')
    return fila['estado'] in ('en_proceso', 'derivada')


class TuboGestionView(RolRequiredMixin, TemplateView):
    roles_permitidos = ROLES_AGENDA
    template_name = 'agenda/tubo.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        actividades = filtrar_contexto_territorial(AtencionCiudadana.objects.filter(
            activo=True, va_al_tubo=True).select_related('delegacion', 'responsable').prefetch_related(
            Prefetch('compromisos', queryset=Compromiso.objects.order_by('fecha_hora'))), self.request)
        gestiones = filtrar_contexto_territorial(GestionSocial.objects.filter(
            activo=True, ingresa_al_tubo=True).select_related('delegacion', 'responsable', 'vecino'), self.request)
        ids = list(actividades.values_list('responsable_id', flat=True)) + list(gestiones.values_list('responsable_id', flat=True))
        form = FiltroTuboForm(self.request.GET, responsables=Perfil.objects.filter(usuario_id__in=ids))
        filas = [_actividad_fila(a) for a in actividades]
        rol = obtener_rol(self.request.user)
        filas += [_gestion_fila(g, self.request.user, rol) for g in gestiones]
        hoy = timezone.localdate()
        if form.is_valid():
            datos = form.cleaned_data
            texto = normalizar_busqueda(datos['q'])
            rut = _normalizar_rut(datos['q'])
            if texto:
                filas = [f for f in filas if any(texto in normalizar_busqueda(f[k]) for k in ('codigo', 'titulo', 'solicitante'))
                    or (rut and rut in _normalizar_rut(f['rut']))]
            if datos['tipo']:
                filas = [f for f in filas if f['tipo'] == datos['tipo']]
            if datos['estado']:
                filas = [f for f in filas if _estado_coincide(f, datos['estado'], hoy)]
            if datos['responsable']:
                filas = [f for f in filas if f['responsable'].pk == datos['responsable'].usuario_id]
            if datos['desde']:
                filas = [f for f in filas if f['fecha'] >= datos['desde']]
            if datos['hasta']:
                filas = [f for f in filas if f['fecha'] <= datos['hasta']]
        else:
            filas = []
        for fila in filas:
            fila['vencido'] = bool(fila['plazo'] and fila['plazo'] < hoy and not fila['cerrado'])
        filas.sort(key=lambda f: (f['plazo'] is None, f['plazo'] or f['fecha'], f['codigo']))
        pagina = Paginator(filas, 25).get_page(self.request.GET.get('page'))
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context.update(form=form, page_obj=pagina, filas=pagina.object_list, query_params=parametros.urlencode())
        return context
