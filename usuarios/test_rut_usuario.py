from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from sgr.test_metas import DatosMetasMixin
from usuarios.models import Rol


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RutUsuarioTests(DatosMetasMixin, TestCase):
    def setUp(self):
        self.entrar('administrador')
        self.url = reverse('usuarios:crear')
        self.datos = {'username': 'persona_rut', 'first_name': 'Persona', 'last_name': 'Prueba',
                      'email': 'prueba@example.com', 'rut': '12345678-5',
                      'rol': Rol.objects.get(codigo='funcionario').pk, 'delegaciones': [self.a.pk]}

    def test_rut_valido_se_guarda_normalizado(self):
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        self.assertEqual(get_user_model().objects.get(username='persona_rut').perfil.rut, '12.345.678-5')

    def test_rut_invalido_o_ausente_no_crea_usuario(self):
        for rut in ('12345678-0', ''):
            with self.subTest(rut=rut):
                respuesta = self.client.post(self.url, {**self.datos, 'rut': rut})
                self.assertFormError(respuesta.context['form'], 'rut', respuesta.context['form'].errors['rut'][0])
                self.assertFalse(get_user_model().objects.filter(username='persona_rut').exists())

    def test_duplicado_normalizado_es_rechazado(self):
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        respuesta = self.client.post(self.url, {**self.datos, 'username': 'otra_persona',
                                                'email': 'otra@example.com', 'rut': '12.345.678-5'})
        self.assertIn('rut', respuesta.context['form'].errors)
        self.assertFalse(get_user_model().objects.filter(username='otra_persona').exists())
