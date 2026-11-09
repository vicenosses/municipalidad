from django.test import TestCase
from django.urls import reverse

from evidencias.models import Evidencia
from sgr.models import AporteIndicador
from sgr.test_aportes import DatosAportesMixin


class ValidacionUnificadaTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.actividad.estado = 'en_proceso'
        self.actividad.save(update_fields=['estado'])
        self.archivo = Evidencia.objects.create(atencion=self.actividad, subido_por=self.usuarios['funcionario'], archivo='prueba.jpg')
        self.entrar('verificador')
        self.url = reverse('evidencias:validar', args=[self.archivo.pk])

    def test_sin_aporte_muestra_validacion_simple(self):
        respuesta = self.client.get(self.url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotContains(respuesta, 'Revisar también el aporte SGR')
        self.assertEqual(self.client.post(self.url, {'accion': 'aprobar'}).status_code, 302)
        self.archivo.refresh_from_db()
        self.assertEqual(self.archivo.estado, 'aprobada')

    def test_aprueba_evidencia_y_aporte_juntos(self):
        aporte = self.asociar()
        self.assertContains(self.client.get(self.url), 'Revisar también el aporte SGR')
        respuesta = self.client.post(self.url, {'accion': 'aprobar', 'evaluar_aporte': 'on',
            'aporte-estado': 'cumple', 'aporte-version': aporte.version})
        self.assertEqual(respuesta.status_code, 302)
        aporte.refresh_from_db()
        self.archivo.refresh_from_db()
        self.assertEqual(aporte.estado, 'cumple')
        self.assertEqual(self.archivo.estado, 'aprobada')

    def test_error_del_aporte_no_guarda_ninguna_decision(self):
        aporte = self.asociar()
        respuesta = self.client.post(self.url, {'accion': 'aprobar', 'evaluar_aporte': 'on',
            'aporte-estado': 'no_cumple', 'aporte-version': aporte.version})
        self.assertEqual(respuesta.status_code, 200)
        self.archivo.refresh_from_db()
        aporte.refresh_from_db()
        self.assertEqual(self.archivo.estado, 'pendiente')
        self.assertEqual(aporte.estado, 'pendiente')

    def test_rechazo_no_permite_aprobar_aporte(self):
        aporte = self.asociar()
        respuesta = self.client.post(self.url, {'accion': 'rechazar', 'evaluar_aporte': 'on',
            'aporte-estado': 'cumple', 'aporte-version': aporte.version})
        self.assertContains(respuesta, 'No puede aprobar el aporte')
        self.archivo.refresh_from_db()
        self.assertEqual(self.archivo.estado, 'pendiente')
