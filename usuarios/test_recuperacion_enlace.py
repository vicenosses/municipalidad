from urllib.parse import urlsplit
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RecuperacionEnlaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='persona', email='persona@example.com', password='AnteriorSegura123!')

    def solicitar(self, email='persona@example.com'):
        return self.client.post(reverse('recuperacion_solicitar'), {'email': email})

    def test_recorrido_completo_y_enlace_de_un_solo_uso(self):
        self.solicitar()
        self.assertEqual(len(mail.outbox), 1)
        link = next(p for p in mail.outbox[0].body.split() if p.startswith('http'))
        path = urlsplit(link).path
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        response = self.client.get(response.url)
        self.assertContains(response, 'Crear nueva contraseña')
        response = self.client.post(response.request['PATH_INFO'], {
            'new_password1': 'NuevaContraseñaSegura123!',
            'new_password2': 'NuevaContraseñaSegura123!',
        })
        self.assertRedirects(response, reverse('login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NuevaContraseñaSegura123!'))
        self.assertContains(self.client.get(path), 'Enlace no válido')

    def test_correo_desconocido_no_revela_cuentas(self):
        response = self.solicitar('desconocido@example.com')
        self.assertRedirects(response, reverse('recuperacion_solicitar'))
        self.assertEqual(len(mail.outbox), 0)

    def test_perfil_inactivo_no_recibe_enlace(self):
        self.user.perfil.activo = False
        self.user.perfil.save()
        self.solicitar()
        self.assertEqual(len(mail.outbox), 0)

    def test_token_invalido(self):
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        url = reverse('recuperacion_enlace', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(self.user.pk)), 'token': 'invalido'})
        self.assertContains(self.client.get(url), 'Enlace no válido')

    def test_correo_html_y_vencimiento_a_los_dos_minutos(self):
        from django.contrib.auth.tokens import default_token_generator
        ahora = default_token_generator._now()
        with patch.object(default_token_generator, '_now', return_value=ahora):
            self.solicitar()
        correo = mail.outbox[0]
        self.assertIn('2 minutos', correo.body)
        self.assertEqual(correo.alternatives[0].mimetype, 'text/html')
        self.assertIn('Ilustre Municipalidad de La Serena', correo.alternatives[0].content)
        self.assertIn('Restablecer contraseña', correo.alternatives[0].content)
        enlace = next(p for p in correo.body.split() if p.startswith('http'))
        with patch.object(default_token_generator, '_now', return_value=ahora + timedelta(seconds=121)):
            self.assertContains(self.client.get(urlsplit(enlace).path), 'Enlace no válido')
