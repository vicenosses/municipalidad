from calendar import monthrange
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from auditoria.utils import registrar_auditoria
from cartas.models import Carta, DocumentoCarta, HistorialCarta
from gestion_social.models import (
    GestionSocial, HistorialGestionSocial, SeguimientoGestionSocial,
)
from hitos.models import Hito, HistorialHito
from operaciones.forms import (
    CambioEstadoForm,
    CartaForm,
    CartaDocumentoForm,
    GestionSocialForm,
    HitoForm,
    SeguimientoGestionSocialForm,
    ROLES_GESTORES,
)
from usuarios.mixins import obtener_rol
from usuarios.sesion import (
    delegaciones_autorizadas,
    filtrar_contexto_territorial,
    get_delegacion_activa,
)

ROLES_VALIDOS = (*ROLES_GESTORES, 'funcionario', 'verificador')
URL_GESTION_SOCIAL_DETALLE = 'atenciones:gestion_social:detalle'
URL_CARTA_DETALLE = 'agenda:cartas:detalle'
URL_HITO_DETALLE = 'agenda:hitos:detalle'
ETIQUETA_GESTION_SOCIAL = 'Gestión social'
ETIQUETA_EN_PROCESO = 'En proceso'


def _puede_editar(user, objeto):
    return obtener_rol(user) in ROLES_GESTORES or objeto.responsable_id == user.pk


def _estado_terminal(objeto):
    if isinstance(objeto, Carta):
        return objeto.estado in (
            Carta.Estado.CERRADA, Carta.Estado.FINALIZADA, Carta.Estado.NO_APLICA,
        )
    if isinstance(objeto, GestionSocial):
        return objeto.estado == GestionSocial.Estado.CERRADA
    return objeto.estado in (Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO)


def _puede_editar_formulario(user, objeto):
    if not _puede_editar(user, objeto) or _estado_terminal(objeto):
        return False
    return not isinstance(objeto, Hito) or obtener_rol(user) in ROLES_GESTORES


def _registrar_historial(objeto, accion, actor, estado_anterior='', motivo=''):
    datos = {
        'accion': accion,
        'actor': actor,
        'estado_anterior': estado_anterior,
        'estado_nuevo': objeto.estado,
        'motivo': motivo,
    }
    if isinstance(objeto, Carta):
        HistorialCarta.objects.create(carta=objeto, **datos)
    elif isinstance(objeto, GestionSocial):
        HistorialGestionSocial.objects.create(gestion=objeto, **datos)
    elif isinstance(objeto, Hito):
        HistorialHito.objects.create(hito=objeto, **datos)


def _sumar_mes(fecha, meses):
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    return fecha.replace(year=anio, month=mes, day=min(fecha.day, monthrange(anio, mes)[1]))


def _crear_proxima_ocurrencia(hito, actor):
    incrementos = {
        Hito.Periodicidad.SEMANAL: timedelta(days=7),
        Hito.Periodicidad.MENSUAL: None,
        Hito.Periodicidad.TRIMESTRAL: None,
        Hito.Periodicidad.ANUAL: None,
    }
    if hito.periodicidad not in incrementos or not hito.repetir_hasta:
        return None
    if hito.periodicidad == Hito.Periodicidad.SEMANAL:
        fecha = hito.fecha_programada + incrementos[hito.periodicidad]
    elif hito.periodicidad == Hito.Periodicidad.MENSUAL:
        fecha = _sumar_mes(hito.fecha_programada, 1)
    elif hito.periodicidad == Hito.Periodicidad.TRIMESTRAL:
        fecha = _sumar_mes(hito.fecha_programada, 3)
    else:
        try:
            fecha = hito.fecha_programada.replace(year=hito.fecha_programada.year + 1)
        except ValueError:
            fecha = hito.fecha_programada.replace(
                year=hito.fecha_programada.year + 1, day=28,
            )
    if fecha > hito.repetir_hasta:
        return None
    raiz = hito.repeticion_padre or hito
    ocurrencia, creada = Hito.objects.get_or_create(
        repeticion_padre=raiz,
        fecha_programada=fecha,
        defaults={
            'titulo': hito.titulo,
            'descripcion': hito.descripcion,
            'actividad': hito.actividad,
            'gestion_social': hito.gestion_social,
            'compromiso': hito.compromiso,
            'territorio': hito.territorio,
            'asignacion_meta': hito.asignacion_meta,
            'responsable': hito.responsable,
            'periodicidad': hito.periodicidad,
            'repetir_hasta': hito.repetir_hasta,
            'creado_por': actor,
        },
    )
    if creada:
        actividades = hito.actividades.all()
        if hito.actividad_id:
            actividades = list(actividades) + [hito.actividad]
        ocurrencia.actividades.set(actividades)
        _registrar_historial(ocurrencia, 'programado', actor)
    return ocurrencia


def _filtrar_propios(queryset, request):
    if obtener_rol(request.user) not in ROLES_GESTORES:
        return queryset.filter(Q(responsable=request.user) | Q(creado_por=request.user))
    return queryset


def _queryset_accesible(model, request):
    if model is Hito:
        queryset = _filtro_hitos(request)
    else:
        queryset = filtrar_contexto_territorial(model.objects.all(), request)
    return _filtrar_propios(queryset, request)


def _excluir_estados_terminales(queryset, model):
    if model is Hito:
        return queryset.exclude(
            estado__in=(Hito.Estado.COMPLETADO, Hito.Estado.CANCELADO),
        )
    if model is Carta:
        return queryset.exclude(
            estado__in=(Carta.Estado.CERRADA, Carta.Estado.FINALIZADA, Carta.Estado.NO_APLICA),
        )
    return queryset.exclude(estado=model.Estado.CERRADA)


def _filtro_hitos(request):
    delegaciones = delegaciones_autorizadas(request.user)
    activa = get_delegacion_activa(request)
    if obtener_rol(request.user) == 'administrador' and activa is None:
        return Hito.objects.all()
    ids = delegaciones.filter(pk=activa.pk).values('pk') if activa else delegaciones.none().values('pk')
    return Hito.objects.filter(
        Q(actividad__delegacion__in=ids)
        | Q(gestion_social__delegacion__in=ids)
        | Q(compromiso__delegacion__in=ids)
    )


class ListaModulo(LoginRequiredMixin, ListView):
    paginate_by = 25
    ordering = '-creado_en'
    estado_parametro = 'estado'

    def filtrar_queryset(self, queryset):
        rol = obtener_rol(self.request.user)
        if rol not in ROLES_VALIDOS:
            raise PermissionDenied
        if self.model is Hito:
            queryset = _filtro_hitos(self.request)
        else:
            queryset = filtrar_contexto_territorial(queryset, self.request)
        queryset = _filtrar_propios(queryset, self.request)

        estado = self.request.GET.get('estado', '').strip()
        q = self.request.GET.get('q', '').strip()
        if estado:
            queryset = queryset.filter(estado=estado)
        if q:
            if self.model is GestionSocial:
                queryset = queryset.filter(
                    Q(codigo__icontains=q) | Q(titulo__icontains=q)
                    | Q(vecino__nombres__icontains=q) | Q(vecino__apellidos__icontains=q)
                )
            elif self.model is Carta:
                queryset = queryset.filter(
                    Q(codigo__icontains=q) | Q(asunto__icontains=q)
                    | Q(vecino__nombres__icontains=q) | Q(vecino__apellidos__icontains=q)
                )
            elif self.model is Hito:
                queryset = queryset.filter(Q(codigo__icontains=q) | Q(titulo__icontains=q))
        return queryset.order_by(self.ordering, 'pk')

    def get_queryset(self):
        return self.filtrar_queryset(self.model.objects.all())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            q=self.request.GET.get('q', ''),
            estado=self.request.GET.get('estado', ''),
            estados=self.model.Estado.choices,
            puede_crear=obtener_rol(self.request.user) in self.roles_creacion,
        )
        return context


class ListaGestionSocial(ListaModulo):
    model = GestionSocial
    template_name = 'operaciones/gestion_social/lista.html'
    context_object_name = 'registros'
    roles_creacion = ROLES_VALIDOS
    ordering = '-fecha_ingreso'

    def get_queryset(self):
        return self.filtrar_queryset(
            GestionSocial.objects.select_related('delegacion', 'territorio', 'responsable')
        ).filter(activo=True)


class ListaCartas(ListaModulo):
    model = Carta
    template_name = 'operaciones/cartas/lista.html'
    context_object_name = 'registros'
    roles_creacion = ROLES_VALIDOS
    ordering = '-fecha_ingreso'

    def get_queryset(self):
        return self.filtrar_queryset(
            Carta.objects.select_related('delegacion', 'territorio', 'responsable')
        ).filter(activo=True)


class ListaHitos(ListaModulo):
    model = Hito
    template_name = 'operaciones/hitos/lista.html'
    context_object_name = 'registros'
    roles_creacion = ('administrador', 'delegado')
    ordering = 'fecha_programada'

    def get_queryset(self):
        return self.filtrar_queryset(
            Hito.objects.select_related(
                'responsable', 'actividad__delegacion', 'gestion_social__delegacion',
                'compromiso__delegacion',
            )
        ).filter(activo=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['hoy'] = timezone.localdate()
        context['limite_proximo'] = timezone.localdate() + timedelta(days=7)
        return context


class CrearModulo(LoginRequiredMixin, CreateView):
    success_message = 'Registro creado correctamente.'
    success_url_name = ''
    roles_creacion = ROLES_VALIDOS

    def dispatch(self, request, *args, **kwargs):
        if obtener_rol(request.user) not in self.roles_creacion:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.creado_por = self.request.user
            if self.object.responsable_id is None:
                self.object.responsable = self.request.user
            self.object.save()
            form.save_m2m()
            _registrar_historial(self.object, 'creado', self.request.user)
            registrar_auditoria(
                self.request, f'crear_{self.audit_modelo}', self.object,
                f'{self.audit_etiqueta} {self.object.codigo} creado.',
            )
        messages.success(self.request, self.success_message)
        return redirect(self.success_url_name)


class CrearGestionSocial(CrearModulo):
    model = GestionSocial
    form_class = GestionSocialForm
    template_name = 'operaciones/gestion_social/form.html'
    success_url_name = 'atenciones:gestion_social:lista'
    audit_modelo = 'gestion_social'
    audit_etiqueta = ETIQUETA_GESTION_SOCIAL


class CrearCarta(CrearModulo):
    model = Carta
    form_class = CartaForm
    template_name = 'operaciones/cartas/form.html'
    success_url_name = 'agenda:cartas:lista'
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class CrearHito(CrearModulo):
    model = Hito
    form_class = HitoForm
    template_name = 'operaciones/hitos/form.html'
    success_url_name = 'agenda:hitos:lista'
    roles_creacion = ('administrador', 'delegado')
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'


class EditarModulo(LoginRequiredMixin, UpdateView):
    def get_queryset(self):
        queryset = _queryset_accesible(self.model, self.request)
        return _excluir_estados_terminales(queryset, self.model)

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not _puede_editar(request.user, self.object):
            raise PermissionDenied
        return response

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        previo = self.object.responsable_id
        estado_anterior = self.object.estado
        motivo = form.cleaned_data.get('motivo_cambio', '').strip()
        with transaction.atomic():
            objeto = form.save()
            _registrar_historial(
                objeto,
                'reasignado' if previo != objeto.responsable_id else 'editado',
                self.request.user,
                estado_anterior=estado_anterior,
                motivo=motivo,
            )
            nota = f'{self.audit_etiqueta} {objeto.codigo} actualizado.'
            if previo != objeto.responsable_id:
                nota += (
                    f' Responsable reasignado de usuario {previo} a {objeto.responsable_id}. '
                    f'Motivo: {motivo}'
                )
            registrar_auditoria(self.request, f'actualizar_{self.audit_modelo}', objeto, nota)
        messages.success(self.request, 'Cambios guardados correctamente.')
        return redirect(self.success_url_name, pk=objeto.pk)


class EditarGestionSocial(EditarModulo):
    model = GestionSocial
    form_class = GestionSocialForm
    template_name = 'operaciones/gestion_social/form.html'
    success_url_name = URL_GESTION_SOCIAL_DETALLE
    audit_modelo = 'gestion_social'
    audit_etiqueta = ETIQUETA_GESTION_SOCIAL


class EditarCarta(EditarModulo):
    model = Carta
    form_class = CartaForm
    template_name = 'operaciones/cartas/form.html'
    success_url_name = URL_CARTA_DETALLE
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class EditarHito(EditarModulo):
    model = Hito
    form_class = HitoForm
    template_name = 'operaciones/hitos/form.html'
    success_url_name = URL_HITO_DETALLE
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
    roles_creacion = ROLES_GESTORES

    def dispatch(self, request, *args, **kwargs):
        if obtener_rol(request.user) not in self.roles_creacion:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class DetalleModulo(LoginRequiredMixin, View):
    model = None
    template_name = ''
    success_url_name = ''
    transiciones = {}

    def get_queryset(self):
        return _queryset_accesible(self.model, self.request).select_related(
            'responsable', 'creado_por',
        )

    def _render_formulario_estado(self, request, objeto, form, estado, puede_editar):
        context = {
            'registro': objeto,
            'puede_editar': puede_editar,
            'transiciones': self.transiciones.get(estado, ()),
            'form_estado': form,
            'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
        }
        context.update(self.contexto_adicional(objeto))
        return render(request, self.template_name, context, status=400)

    def contexto_adicional(self, objeto):
        return {}

    @staticmethod
    def _actualizar_estado_carta(objeto, estado, form):
        if estado in (Carta.Estado.RESPONDIDA, Carta.Estado.APROBADA):
            objeto.respuesta = form.cleaned_data['respuesta'].strip()
            objeto.fecha_respuesta = timezone.localdate()
        elif estado in (Carta.Estado.EN_PROCESO, Carta.Estado.DERIVADA):
            objeto.fecha_respuesta = None
        if estado in (Carta.Estado.CERRADA, Carta.Estado.FINALIZADA, Carta.Estado.NO_APLICA):
            objeto.fecha_cierre = timezone.localdate()
        else:
            objeto.fecha_cierre = None

    @staticmethod
    def _actualizar_estado_hito(objeto, estado, form):
        if estado == Hito.Estado.COMPLETADO:
            objeto.fecha_completada = form.cleaned_data['fecha_completada']
            if not objeto.fecha_completada:
                form.add_error('fecha_completada', 'Indique la fecha de término.')
        elif estado == Hito.Estado.CANCELADO:
            objeto.motivo_cambio = form.cleaned_data['motivo'].strip()
            if not objeto.motivo_cambio:
                form.add_error('motivo', 'Indique el motivo de cancelación.')
        else:
            objeto.fecha_completada = None

    def _actualizar_campos_estado(self, objeto, estado, form):
        objeto.estado = estado
        if isinstance(objeto, Carta):
            self._actualizar_estado_carta(objeto, estado, form)
        elif isinstance(objeto, Hito):
            self._actualizar_estado_hito(objeto, estado, form)
        elif isinstance(objeto, GestionSocial):
            objeto.fecha_cierre = (
                timezone.localdate() if estado == GestionSocial.Estado.CERRADA else None
            )

    def get(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        objeto = get_object_or_404(self.get_queryset(), pk=pk)
        context = {
            'registro': objeto,
            'puede_editar': _puede_editar_formulario(request.user, objeto),
            'transiciones': self.transiciones.get(objeto.estado, ()),
            'form_estado': CambioEstadoForm(
                choices=self.transiciones.get(objeto.estado, ()),
            ),
            'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
        }
        context.update(self.contexto_adicional(objeto))
        return render(request, self.template_name, context)

    @transaction.atomic
    def post(self, request, pk):
        objeto = get_object_or_404(self.get_queryset().select_for_update(), pk=pk)
        if not _puede_editar(request.user, objeto):
            raise PermissionDenied
        form = CambioEstadoForm(
            request.POST, choices=self.transiciones.get(objeto.estado, ()),
        )
        if not form.is_valid():
            return self._render_formulario_estado(
                request, objeto, form, objeto.estado,
                _puede_editar_formulario(request.user, objeto),
            )
        anterior = objeto.estado
        estado = form.cleaned_data['estado']
        self._actualizar_campos_estado(objeto, estado, form)
        if form.errors:
            return self._render_formulario_estado(request, objeto, form, anterior, True)
        with transaction.atomic():
            objeto.save()
            motivo = form.cleaned_data.get('motivo', '').strip()
            _registrar_historial(
                objeto, 'cambio_estado', request.user,
                estado_anterior=anterior, motivo=motivo,
            )
            if isinstance(objeto, Hito) and estado == Hito.Estado.COMPLETADO:
                _crear_proxima_ocurrencia(objeto, request.user)
            registrar_auditoria(
                request, f'cambiar_estado_{self.audit_modelo}', objeto,
                f'{self.audit_etiqueta} {objeto.codigo}: {anterior} → {estado}.',
            )
        messages.success(request, 'Estado actualizado correctamente.')
        return redirect(self.success_url_name, pk=objeto.pk)


class DetalleGestionSocial(DetalleModulo):
    model = GestionSocial
    template_name = 'operaciones/gestion_social/detalle.html'
    success_url_name = URL_GESTION_SOCIAL_DETALLE
    audit_modelo = 'gestion_social'
    audit_etiqueta = ETIQUETA_GESTION_SOCIAL
    transiciones = {
        GestionSocial.Estado.REGISTRADA: (
            (GestionSocial.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
            (GestionSocial.Estado.DERIVADA, 'Derivada'),
        ),
        GestionSocial.Estado.EN_PROCESO: (
            (GestionSocial.Estado.PENDIENTE_ANTECEDENTES, 'Pendiente de antecedentes'),
            (GestionSocial.Estado.DERIVADA, 'Derivada'),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
        GestionSocial.Estado.PENDIENTE_ANTECEDENTES: (
            (GestionSocial.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
        GestionSocial.Estado.DERIVADA: (
            (GestionSocial.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
            (GestionSocial.Estado.CERRADA, 'Cerrada'),
        ),
    }

    def contexto_adicional(self, objeto):
        return {
            'seguimientos': objeto.seguimientos.select_related('actor'),
            'form_seguimiento': SeguimientoGestionSocialForm(),
            'tiempo_gestion_dias': (
                (objeto.fecha_cierre - objeto.fecha_ingreso).days
                if objeto.fecha_cierre else (timezone.localdate() - objeto.fecha_ingreso).days
            ),
        }


class DetalleCarta(DetalleModulo):
    model = Carta
    template_name = 'operaciones/cartas/detalle.html'
    success_url_name = URL_CARTA_DETALLE
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'
    transiciones = {
        Carta.Estado.INGRESADA: (
            (Carta.Estado.DERIVADA, 'Derivada'),
            (Carta.Estado.ASIGNADA, 'Asignada'),
            (Carta.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
            (Carta.Estado.NO_APLICA, 'No aplica'),
        ),
        Carta.Estado.DERIVADA: ((Carta.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),),
        Carta.Estado.ASIGNADA: (
            (Carta.Estado.DERIVADA, 'Derivada'),
            (Carta.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
        ),
        Carta.Estado.EN_PROCESO: (
            (Carta.Estado.RESPONDIDA, 'Respondida'),
            (Carta.Estado.APROBADA, 'Aprobada'),
            (Carta.Estado.NO_APLICA, 'No aplica'),
        ),
        Carta.Estado.RESPONDIDA: (
            (Carta.Estado.APROBADA, 'Aprobada'),
            (Carta.Estado.FINALIZADA, 'Finalizada'),
            (Carta.Estado.CERRADA, 'Cerrada'),
            (Carta.Estado.EN_PROCESO, 'Reabrir en proceso'),
        ),
        Carta.Estado.APROBADA: (
            (Carta.Estado.FINALIZADA, 'Finalizada'),
            (Carta.Estado.EN_PROCESO, 'Reabrir en proceso'),
        ),
    }

    def contexto_adicional(self, objeto):
        return {
            'documentos': objeto.documentos.select_related('subido_por'),
            'form_documento': CartaDocumentoForm(),
        }


class RegistrarSeguimientoGestionSocial(LoginRequiredMixin, View):
    def post(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        gestion = get_object_or_404(_queryset_accesible(GestionSocial, request), pk=pk)
        if not _puede_editar_formulario(request.user, gestion):
            raise PermissionDenied
        form = SeguimientoGestionSocialForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, 'operaciones/gestion_social/detalle.html', {
                'registro': gestion,
                'puede_editar': True,
                'puede_desactivar': obtener_rol(request.user) in ROLES_GESTORES,
                'transiciones': DetalleGestionSocial.transiciones.get(gestion.estado, ()),
                'form_estado': CambioEstadoForm(
                    choices=DetalleGestionSocial.transiciones.get(gestion.estado, ()),
                ),
                'seguimientos': gestion.seguimientos.select_related('actor'),
                'form_seguimiento': form,
                'tiempo_gestion_dias': (timezone.localdate() - gestion.fecha_ingreso).days,
            }, status=400)
        with transaction.atomic():
            seguimiento = form.save(commit=False)
            seguimiento.gestion = gestion
            seguimiento.actor = request.user
            seguimiento.save()
            HistorialGestionSocial.objects.create(
                gestion=gestion,
                accion=seguimiento.get_tipo_display().lower(),
                estado_anterior=gestion.estado,
                estado_nuevo=gestion.estado,
                motivo=seguimiento.observaciones or seguimiento.resultado,
                actor=request.user,
            )
            registrar_auditoria(
                request, 'seguimiento_gestion_social', gestion,
                f'{seguimiento.get_tipo_display()} registrado para {gestion.codigo}.',
            )
        messages.success(request, 'Seguimiento social registrado.')
        return redirect(URL_GESTION_SOCIAL_DETALLE, pk=gestion.pk)


class AgregarDocumentoCarta(LoginRequiredMixin, View):
    def post(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        carta = get_object_or_404(_queryset_accesible(Carta, request), pk=pk)
        if not _puede_editar_formulario(request.user, carta):
            raise PermissionDenied
        form = CartaDocumentoForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, 'Seleccione un documento y corrija los campos indicados.')
            return redirect(URL_CARTA_DETALLE, pk=carta.pk)
        with transaction.atomic():
            documento = form.save(commit=False)
            documento.carta = carta
            documento.subido_por = request.user
            documento.save()
            HistorialCarta.objects.create(
                carta=carta,
                accion='documento_agregado',
                estado_anterior=carta.estado,
                estado_nuevo=carta.estado,
                motivo=documento.descripcion,
                actor=request.user,
            )
            registrar_auditoria(request, 'agregar_documento_carta', carta, 'Documento adjuntado.')
        messages.success(request, 'Documento agregado a la carta.')
        return redirect(URL_CARTA_DETALLE, pk=carta.pk)


class DescargarDocumentoCarta(LoginRequiredMixin, View):
    def get(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        documento = get_object_or_404(
            DocumentoCarta.objects.select_related('carta'),
            pk=pk,
            carta__in=_queryset_accesible(Carta, request),
        )
        if not documento.archivo:
            raise Http404
        respuesta = FileResponse(
            documento.archivo.open('rb'),
            as_attachment=True,
            filename=documento.archivo.name.rsplit('/', 1)[-1],
            content_type='application/octet-stream',
        )
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta


class DescargarEvidenciaSocial(LoginRequiredMixin, View):
    def get(self, request, pk):
        if obtener_rol(request.user) not in ROLES_VALIDOS:
            raise PermissionDenied
        seguimiento = get_object_or_404(
            SeguimientoGestionSocial.objects.select_related('gestion'),
            pk=pk,
            gestion__in=_queryset_accesible(GestionSocial, request),
        )
        if not seguimiento.evidencia:
            raise Http404
        respuesta = FileResponse(
            seguimiento.evidencia.open('rb'),
            as_attachment=True,
            filename=seguimiento.evidencia.name.rsplit('/', 1)[-1],
            content_type='application/octet-stream',
        )
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta


class DetalleHito(DetalleModulo):
    model = Hito
    template_name = 'operaciones/hitos/detalle.html'
    success_url_name = URL_HITO_DETALLE
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
    transiciones = {
        Hito.Estado.PENDIENTE: (
            (Hito.Estado.EN_PROCESO, ETIQUETA_EN_PROCESO),
            (Hito.Estado.CANCELADO, 'Cancelar'),
        ),
        Hito.Estado.EN_PROCESO: (
            (Hito.Estado.COMPLETADO, 'Completado'),
            (Hito.Estado.CANCELADO, 'Cancelar'),
        ),
    }


class DesactivarModulo(LoginRequiredMixin, View):
    model = None
    detail_url_name = ''
    audit_modelo = ''
    audit_etiqueta = ''

    def post(self, request, pk):
        if obtener_rol(request.user) not in ROLES_GESTORES:
            raise PermissionDenied
        if self.model is Hito:
            queryset = _filtro_hitos(request)
        else:
            queryset = filtrar_contexto_territorial(self.model.objects.all(), request)
        objeto = get_object_or_404(queryset, pk=pk)
        with transaction.atomic():
            objeto.activo = False
            objeto.save(update_fields=['activo', 'actualizado_en'])
            registrar_auditoria(
                request, f'desactivar_{self.audit_modelo}', objeto,
                f'{self.audit_etiqueta} {objeto.codigo} desactivado.',
            )
        messages.success(request, 'Registro desactivado correctamente.')
        return redirect(self.detail_url_name, pk=objeto.pk)


class DesactivarGestionSocial(DesactivarModulo):
    model = GestionSocial
    detail_url_name = URL_GESTION_SOCIAL_DETALLE
    audit_modelo = 'gestion_social'
    audit_etiqueta = ETIQUETA_GESTION_SOCIAL


class DesactivarCarta(DesactivarModulo):
    model = Carta
    detail_url_name = URL_CARTA_DETALLE
    audit_modelo = 'carta'
    audit_etiqueta = 'Carta'


class DesactivarHito(DesactivarModulo):
    model = Hito
    detail_url_name = URL_HITO_DETALLE
    audit_modelo = 'hito'
    audit_etiqueta = 'Hito'
