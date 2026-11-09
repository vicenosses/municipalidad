from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from sgr.test_metas import DatosMetasMixin


class BarraSuperiorTests(DatosMetasMixin, TestCase):
    def test_inicio_indica_delegacion_activa_o_contexto_global(self):
        self.entrar('funcionario')
        respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, 'Delegación activa:')
        self.assertContains(respuesta, self.a.nombre)
        self.entrar('administrador')
        respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, 'Todas las delegaciones')

    def test_login_sin_barra_antigua_y_navegacion_en_sesion(self):
        respuesta = self.client.get(reverse('login'))
        self.assertNotContains(respuesta, 'Navegación principal')
        self.assertContains(respuesta, 'Iniciar sesión')
        self.entrar('funcionario')
        self.assertContains(self.client.get(reverse('home')), 'Navegación principal')

    def test_login_con_sesion_iniciada_redirige_a_inicio(self):
        self.entrar('funcionario')
        respuesta = self.client.get(reverse('login'))
        self.assertRedirects(respuesta, reverse('home'))

    def test_login_sin_sesion_indica_no_guardar_y_revalida_historial(self):
        respuesta = self.client.get(reverse('login'))
        self.assertIn('no-store', respuesta['Cache-Control'])
        self.assertContains(respuesta, "event.persisted")

    def test_usuario_y_periodo_vigente_en_barra(self):
        self.entrar('funcionario')
        with patch('django.utils.timezone.localdate', return_value=date(2026, 10, 1)):
            respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, 'Trimestre vigente:')
        self.assertContains(respuesta, self.periodo.nombre)
        self.assertContains(respuesta, '01/10/2026')
        self.assertContains(respuesta, '31/12/2026')
        self.assertContains(respuesta, 'Termina:')
        self.assertContains(respuesta, 'Cerrar sesión', count=1)
        self.assertContains(respuesta, self.usuarios['funcionario'].username)

    def test_sin_periodo_vigente_no_muestra_dato_inventado(self):
        self.entrar('funcionario')
        with patch('django.utils.timezone.localdate', return_value=date(2030, 1, 1)):
            respuesta = self.client.get(reverse('home'))
        self.assertContains(respuesta, 'No hay un período activo vigente')
        self.assertIsNone(respuesta.context['sesion_periodo'])
