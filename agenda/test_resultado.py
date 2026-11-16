from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from agenda.models import Compromiso, HistorialCompromiso
from sgr.test_metas import DatosMetasMixin


class ResultadoCompromisoTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.compromiso = Compromiso.objects.create(
            titulo='Compromiso territorial', fecha_hora=timezone.now() + timedelta(days=3),
            delegacion=cls.a, responsable=cls.usuarios['funcionario'],
            creado_por=cls.usuarios['funcionario'], resultado='Resultado anterior',
        )

    def setUp(self):
        self.editar = reverse('agenda:editar', args=[self.compromiso.pk])
        self.detalle = reverse('agenda:detalle', args=[self.compromiso.pk])

    def test_responsable_registra_resultado_y_queda_en_historial(self):
        self.entrar('funcionario')
        self.assertContains(self.client.get(self.editar), 'Resultado')
        respuesta = self.client.post(self.editar, {'estado': 'ingresado', 'resultado': 'Se resolvió la solicitud.'})
        self.assertRedirects(respuesta, self.detalle)
        self.compromiso.refresh_from_db()
        self.assertEqual(self.compromiso.resultado, 'Se resolvió la solicitud.')
        cambio = HistorialCompromiso.objects.get(compromiso=self.compromiso, campo='resultado')
        self.assertEqual((cambio.valor_anterior, cambio.valor_nuevo, cambio.realizado_por),
                         ('Resultado anterior', 'Se resolvió la solicitud.', self.usuarios['funcionario']))
        self.assertContains(self.client.get(self.detalle), 'Se resolvió la solicitud.')

    def test_formulario_antiguo_conserva_resultado(self):
        self.entrar('funcionario')
        respuesta = self.client.post(self.editar, {'estado': 'ingresado'})
        self.assertRedirects(respuesta, self.detalle)
        self.compromiso.refresh_from_db()
        self.assertEqual(self.compromiso.resultado, 'Resultado anterior')
        self.assertFalse(HistorialCompromiso.objects.filter(compromiso=self.compromiso, campo='resultado').exists())

    def test_tercero_no_puede_modificar_y_texto_se_muestra_seguro(self):
        self.entrar('verificador')
        self.assertEqual(self.client.post(self.editar, {'estado': 'ingresado', 'resultado': 'Cambio'}).status_code, 403)
        self.compromiso.resultado = '<script>alert(1)</script>'
        self.compromiso.save(update_fields=['resultado'])
        self.entrar('funcionario')
        respuesta = self.client.get(self.detalle)
        self.assertContains(respuesta, '&lt;script&gt;alert(1)&lt;/script&gt;', html=False)
        self.assertNotContains(respuesta, '<script>alert(1)</script>')

    def test_api_muestra_resultado_en_detalle_y_lo_oculta_en_lista(self):
        api = APIClient()
        api.force_authenticate(self.usuarios['funcionario'])
        detalle = api.get(f'/api/v1/compromisos/{self.compromiso.pk}/')
        self.assertEqual(detalle.status_code, 200)
        self.assertEqual(detalle.data['resultado'], 'Resultado anterior')
        lista = api.get('/api/v1/compromisos/')
        self.assertEqual(lista.status_code, 200)
        registro = next(item for item in lista.data['results'] if item['id'] == self.compromiso.pk)
        self.assertIsNone(registro['resultado'])
