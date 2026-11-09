from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from usuarios.tokens_activacion import token_activacion
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from sgr.test_metas import DatosMetasMixin
from usuarios.models import Rol


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ActivacionCuentaTests(DatosMetasMixin, TestCase):
    def crear_usuario(self):
        self.entrar('administrador')
        return self.client.post(reverse('usuarios:crear'), {
            'username': 'nueva_persona', 'first_name': 'Persona', 'last_name': 'Nueva', 'rut': '12345678-5',
            'email': 'nueva@example.com', 'rol': Rol.objects.get(codigo='funcionario').pk,
            'delegaciones': [self.a.pk],
        })

    def test_creacion_y_activacion_unica(self):
        self.assertEqual(self.crear_usuario().status_code, 302)
        usuario = get_user_model().objects.get(username='nueva_persona')
        self.assertFalse(usuario.is_active)
        self.assertFalse(usuario.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        enlace = next(p for p in mail.outbox[0].body.split() if p.startswith('http'))
        ruta = urlsplit(enlace).path
        self.client.logout()
        respuesta = self.client.get(ruta)
        self.assertEqual(respuesta.status_code, 302)
        respuesta = self.client.get(respuesta.url)
        self.assertContains(respuesta, 'Activar cuenta')
        self.assertEqual(self.client.post(respuesta.request['PATH_INFO'], {
            'new_password1': 'ContrasenaSegura2026!', 'new_password2': 'ContrasenaSegura2026!',
        }).status_code, 302)
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_active)
        self.assertTrue(usuario.check_password('ContrasenaSegura2026!'))
        self.assertContains(self.client.get(ruta), 'Enlace no válido')

    def test_enlace_expirado_y_reenvio(self):
        ahora = token_activacion._now()
        with patch.object(token_activacion, '_now', return_value=ahora):
            self.crear_usuario()
        usuario = get_user_model().objects.get(username='nueva_persona')
        ruta = urlsplit(next(p for p in mail.outbox[0].body.split() if p.startswith('http'))).path
        with patch.object(token_activacion, '_now', return_value=ahora + timedelta(seconds=599)):
            self.assertEqual(self.client.get(ruta).status_code, 302)
        with patch.object(token_activacion, '_now', return_value=ahora + timedelta(seconds=601)):
            self.assertContains(self.client.get(ruta), 'Enlace no válido')
        self.assertEqual(self.client.post(reverse('usuarios:reenviar_activacion', args=[usuario.perfil.pk])).status_code, 302)
        self.assertEqual(len(mail.outbox), 2)

    def test_fallo_correo_conserva_cuenta_pendiente(self):
        with patch('usuarios.auth_views.enviar_activacion', side_effect=OSError('Fallo de prueba')):
            respuesta = self.crear_usuario()
        self.assertEqual(respuesta.status_code, 302)
        usuario = get_user_model().objects.get(username='nueva_persona')
        self.assertFalse(usuario.is_active)
        self.assertFalse(usuario.has_usable_password())

    def test_delegado_no_reenvia_a_cuenta_fuera_de_delegacion(self):
        self.crear_usuario()
        usuario = get_user_model().objects.get(username='nueva_persona')
        usuario.perfil.delegaciones.set([self.b])
        usuario.perfil.delegacion = self.b
        usuario.perfil.save(update_fields=['delegacion'])
        self.entrar('delegado')
        respuesta = self.client.post(reverse('usuarios:reenviar_activacion', args=[usuario.perfil.pk]))
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(len(mail.outbox), 1)

    def test_activar_desde_mantenedor_no_salta_creacion_de_clave(self):
        self.crear_usuario()
        usuario = get_user_model().objects.get(username='nueva_persona')
        self.client.post(reverse('usuarios:desactivar', args=[usuario.perfil.pk]), {'activo': 'true'})
        usuario.refresh_from_db()
        self.assertFalse(usuario.is_active)
        self.assertFalse(usuario.has_usable_password())
