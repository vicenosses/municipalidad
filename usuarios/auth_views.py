import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from usuarios.forms import (
    CodigoRecuperacionForm,
    LoginUsuarioCorreoForm,
    NuevaContrasenaForm,
    SolicitudRecuperacionForm,
)
from usuarios.models import CodigoRecuperacion

MENSAJE_GENERICO = 'Si el correo está registrado, enviamos un código de verificación.'
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
    def dispatch(self, request, *args, **kwargs):
        registro = CodigoRecuperacion.objects.filter(
            pk=request.session.get('recuperacion_id')
        ).first()
        if not registro or not request.session.get('recuperacion_ok'):
            return redirect('recuperacion_solicitar')
        self.registro = registro
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        form = NuevaContrasenaForm(user=self.registro.usuario)
        return render(request, 'recuperacion/nueva.html', _ctx({'form': form}))

    def post(self, request):
        form = NuevaContrasenaForm(user=self.registro.usuario, data=request.POST)
        if not form.is_valid():
            return render(request, 'recuperacion/nueva.html', _ctx({'form': form}))
        form.save()
        self.registro.usado = True
        self.registro.save(update_fields=['usado'])
        request.session.pop('recuperacion_id', None)
        request.session.pop('recuperacion_ok', None)
        request.session.pop('recuperacion_pendiente', None)
        messages.success(request, 'Contraseña actualizada. Puede ingresar.')
        return redirect('login')
