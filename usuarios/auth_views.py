import secrets
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, PasswordResetConfirmView
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.urls import reverse, reverse_lazy
from django.views import View

from usuarios.forms import (
    CodigoRecuperacionForm,
    LoginUsuarioCorreoForm,
    NuevaContrasenaForm,
    SolicitudRecuperacionForm,
)
from usuarios.models import CodigoRecuperacion

MENSAJE_GENERICO = 'Si existe una cuenta habilitada para ese correo, recibirás un enlace de recuperación.'
logger = logging.getLogger(__name__)
VIGENCIA_MINUTOS = 15
MAX_INTENTOS = 5


class LoginSGRView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginUsuarioCorreoForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['usar_swal_mensajes'] = True
        return context


def _ctx(extra=None):
    data = {'usar_swal_mensajes': True}
    if extra:
        data.update(extra)
    return data


def _usuario_puede_recuperar(user):
    if user is None or not user.is_active:
        return False
    perfil = getattr(user, 'perfil', None)
    if perfil is not None and not perfil.activo:
        return False
    return True


class RecuperacionSolicitarView(View):
    def get(self, request):
        return render(request, 'recuperacion/solicitar.html', _ctx({'form': SolicitudRecuperacionForm()}))

    def post(self, request):
        form = SolicitudRecuperacionForm(request.POST)
        if not form.is_valid():
            return render(request, 'recuperacion/solicitar.html', _ctx({'form': form}))
        email = form.cleaned_data['email']
        user = User.objects.filter(email__iexact=email).exclude(email='').first()
        if _usuario_puede_recuperar(user) and user.has_usable_password():
            enlace = request.build_absolute_uri(reverse('recuperacion_enlace', kwargs={
                'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
                'token': default_token_generator.make_token(user),
            }))
            try:
                send_mail(
                    'Recuperación de contraseña SGR',
                    f'Ilustre Municipalidad de La Serena\nSistema de Gestión de Resultados\n\n'
                    f'Para establecer una nueva contraseña, abre este enlace:\n\n{enlace}\n\n'
                    'El enlace vence en 2 minutos. Si no solicitaste este cambio, ignora este mensaje.',
                    settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
                    html_message=render_to_string('recuperacion/correo.html', {'enlace': enlace}),
                )
            except Exception:
                logger.exception('No se pudo enviar el correo de recuperación.')
        messages.info(request, MENSAJE_GENERICO)
        return redirect('recuperacion_solicitar')


class RecuperacionEnlaceView(PasswordResetConfirmView):
    template_name = 'recuperacion/enlace.html'
    form_class = NuevaContrasenaForm
    success_url = reverse_lazy('login')

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        return user if _usuario_puede_recuperar(user) else None

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Contraseña actualizada. Puede ingresar.')
        return response


class RecuperacionSolicitarCodigoAnteriorView(View):
    def post(self, request):
        form = SolicitudRecuperacionForm(request.POST)
        if not form.is_valid():
            return redirect('recuperacion_solicitar')
        email = form.cleaned_data['email']
        user = User.objects.filter(email__iexact=email).exclude(email='').first()
        request.session['recuperacion_pendiente'] = True
        request.session.pop('recuperacion_ok', None)
        request.session.pop('recuperacion_id', None)
        if _usuario_puede_recuperar(user):
            CodigoRecuperacion.objects.filter(usuario=user, usado=False).update(usado=True)
            codigo = f'{secrets.randbelow(1_000_000):06d}'
            registro = CodigoRecuperacion.objects.create(
                usuario=user,
                codigo_hash=make_password(codigo),
                expira=timezone.now() + timedelta(minutes=VIGENCIA_MINUTOS),
            )
            request.session['recuperacion_id'] = registro.pk
            send_mail(
                'Código de recuperación SGR',
                f'Su código de verificación es: {codigo}. Vence en {VIGENCIA_MINUTOS} minutos.',
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=True,
            )
        messages.info(request, MENSAJE_GENERICO)
        return redirect('recuperacion_codigo')


class RecuperacionCodigoView(View):
    def get(self, request):
        if not request.session.get('recuperacion_pendiente'):
            return redirect('recuperacion_solicitar')
        return render(request, 'recuperacion/codigo.html', _ctx({'form': CodigoRecuperacionForm()}))

    def post(self, request):
        if not request.session.get('recuperacion_pendiente'):
            return redirect('recuperacion_solicitar')
        form = CodigoRecuperacionForm(request.POST)
        if not form.is_valid():
            return render(request, 'recuperacion/codigo.html', _ctx({'form': form}))
        registro = CodigoRecuperacion.objects.filter(
            pk=request.session.get('recuperacion_id')
        ).first()
        if not registro:
            messages.error(request, 'Código incorrecto. Solicite uno nuevo si no lo recibió.')
            return render(request, 'recuperacion/codigo.html', _ctx({'form': form}))
        if registro.usado or registro.expira < timezone.now():
            registro.usado = True
            registro.save(update_fields=['usado'])
            messages.error(request, 'El código expiró. Solicite uno nuevo.')
            return redirect('recuperacion_solicitar')
        if registro.intentos >= MAX_INTENTOS:
            registro.usado = True
            registro.save(update_fields=['usado'])
            messages.error(request, 'Se agotaron los intentos. Solicite un código nuevo.')
            return redirect('recuperacion_solicitar')
        if not check_password(form.cleaned_data['codigo'], registro.codigo_hash):
            registro.intentos += 1
            if registro.intentos >= MAX_INTENTOS:
                registro.usado = True
                registro.save(update_fields=['intentos', 'usado'])
                messages.error(request, 'Se agotaron los intentos. Solicite un código nuevo.')
                return redirect('recuperacion_solicitar')
            registro.save(update_fields=['intentos'])
            restantes = MAX_INTENTOS - registro.intentos
            messages.error(request, f'Código incorrecto. Intentos restantes: {restantes}.')
            return render(request, 'recuperacion/codigo.html', _ctx({'form': form}))
        request.session['recuperacion_ok'] = True
        return redirect('recuperacion_nueva')


class RecuperacionNuevaView(View):
    def rechazar_recuperacion(self, request):
        for clave in ('recuperacion_id', 'recuperacion_ok', 'recuperacion_pendiente'):
            request.session.pop(clave, None)
        return redirect('recuperacion_solicitar')

    def codigo_vigente(self, registro):
        return (
            registro is not None and not registro.usado and registro.expira > timezone.now()
            and _usuario_puede_recuperar(registro.usuario)
        )

    def dispatch(self, request, *args, **kwargs):
        registro = CodigoRecuperacion.objects.select_related('usuario').filter(
            pk=request.session.get('recuperacion_id')
        ).first()
        if not request.session.get('recuperacion_ok') or not self.codigo_vigente(registro):
            return self.rechazar_recuperacion(request)
        self.registro = registro
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = NuevaContrasenaForm(user=self.registro.usuario)
        return render(request, 'recuperacion/nueva.html', _ctx({'form': form}))

    @transaction.atomic
    def post(self, request):
        # Se vuelve a leer después del bloqueo: otra sesión pudo consumirlo.
        registro = CodigoRecuperacion.objects.select_for_update().select_related('usuario').filter(
            pk=self.registro.pk).first()
        if not self.codigo_vigente(registro):
            return self.rechazar_recuperacion(request)
        form = NuevaContrasenaForm(user=registro.usuario, data=request.POST)
        if not form.is_valid():
            return render(request, 'recuperacion/nueva.html', _ctx({'form': form}))
        consumidos = CodigoRecuperacion.objects.filter(
            pk=registro.pk, usado=False, expira__gt=timezone.now()).update(usado=True)
        if consumidos != 1:
            return self.rechazar_recuperacion(request)
        form.save()
        request.session.pop('recuperacion_id', None)
        request.session.pop('recuperacion_ok', None)
        request.session.pop('recuperacion_pendiente', None)
        messages.success(request, 'Contraseña actualizada. Puede ingresar.')
        return redirect('login')
