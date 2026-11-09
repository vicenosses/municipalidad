from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import IntentosIngreso


class LimiteIngresoTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user('persona', email='persona@example.com', password='Segura123!')
        self.url = reverse('login')

    def test_bloquea_ambos_identificadores_y_expira(self):
        ahora = timezone.now()
        with patch('usuarios.limite_ingreso.timezone.now', return_value=ahora):
            for _ in range(5):
                self.client.post(self.url, {'username': 'persona', 'password': 'incorrecta'})
            respuesta = self.client.post(self.url, {'username': 'persona@example.com', 'password': 'Segura123!'})
            self.assertContains(respuesta, 'Demasiados intentos fallidos')
            self.assertNotIn('_auth_user_id', self.client.session)
        with patch('usuarios.limite_ingreso.timezone.now', return_value=ahora + timedelta(minutes=16)):
            respuesta = self.client.post(self.url, {'username': 'persona', 'password': 'Segura123!'})
            self.assertEqual(respuesta.status_code, 302)
            self.assertEqual(int(self.client.session['_auth_user_id']), self.usuario.pk)
            self.assertFalse(IntentosIngreso.objects.exists())

    def test_identificador_desconocido_tambien_se_bloquea(self):
        for _ in range(5):
            self.client.post(self.url, {'username': 'desconocido', 'password': 'incorrecta'})
        respuesta = self.client.post(self.url, {'username': 'desconocido', 'password': 'incorrecta'})
        self.assertContains(respuesta, 'Demasiados intentos fallidos')
