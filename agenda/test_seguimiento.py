from datetime import timedelta
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from agenda.models import Compromiso, HistorialCompromiso
from auditoria.models import RegistroAuditoria
from sgr.test_metas import DatosMetasMixin


class SeguimientoCompromisoTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.compromiso = Compromiso.objects.create(titulo='Seguimiento territorial', fecha_hora=timezone.now()+timedelta(days=3),
            delegacion=cls.a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'])
        cls.ajeno = Compromiso.objects.create(titulo='Otra delegación', fecha_hora=timezone.now()+timedelta(days=3),
            delegacion=cls.b, responsable=cls.usuarios['funcionario'])

    def setUp(self):
        self.url = reverse('agenda:agregar_seguimiento', args=[self.compromiso.pk])
        self.detalle = reverse('agenda:detalle', args=[self.compromiso.pk])
        self.api_url = f'/api/v1/compromisos/{self.compromiso.pk}/seguimientos/'
        self.datos = {'tipo':'avance', 'descripcion':'Se revisó la solicitud.'}

    def test_pagina_crea_evento_y_muestra_autor_sin_exponer_detalle_en_auditoria(self):
        self.entrar('funcionario')
        self.assertContains(self.client.get(self.detalle), 'Registrar avance u observación')
        respuesta = self.client.post(self.url, self.datos)
        self.assertRedirects(respuesta, self.detalle)
        evento = HistorialCompromiso.objects.get(compromiso=self.compromiso, campo='avance')
        self.assertEqual(evento.realizado_por, self.usuarios['funcionario'])
        self.assertEqual(evento.valor_nuevo, self.datos['descripcion'])
        self.assertContains(self.client.get(self.detalle), self.datos['descripcion'])
        log = RegistroAuditoria.objects.get(accion='agregar_seguimiento_compromiso', objeto_id=str(self.compromiso.pk))
        self.assertNotIn(evento.valor_nuevo, log.descripcion)

    def test_solo_responsable_o_gestor_en_alcance_puede_agregar(self):
        self.entrar('verificador')
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
        self.entrar('delegado')
        ajeno = reverse('agenda:agregar_seguimiento', args=[self.ajeno.pk])
        self.assertEqual(self.client.post(ajeno, self.datos).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        self.compromiso.estado = Compromiso.Estado.REALIZADO
        self.compromiso.save(update_fields=['estado'])
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 403)
        self.assertEqual(HistorialCompromiso.objects.filter(compromiso=self.compromiso, campo='avance').count(), 1)

    def test_validacion_y_csrf(self):
        self.entrar('funcionario')
        respuesta = self.client.post(self.url, {'tipo':'avance', 'descripcion':'   '})
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('descripcion', respuesta.context['form_seguimiento'].errors)
        self.assertContains(respuesta, 'id_descripcion', status_code=400)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['funcionario'])
        self.assertEqual(cliente.post(self.url, self.datos).status_code, 403)
        self.assertFalse(HistorialCompromiso.objects.exists())

    def test_api_comparte_historial_y_bloquea_operaciones_no_autorizadas(self):
        api = APIClient()
        self.assertEqual(api.get(self.api_url).status_code, 401)
        api.force_authenticate(self.usuarios['funcionario'])
        respuesta = api.post(self.api_url, dict(self.datos, realizado_por=self.usuarios['delegado'].pk), format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        self.assertEqual(respuesta.data['autor']['id'], self.usuarios['funcionario'].pk)
        self.assertEqual(api.get(self.api_url).data['count'], 1)
        self.entrar('funcionario')
        self.assertContains(self.client.get(self.detalle), self.datos['descripcion'])
        api.force_authenticate(self.usuarios['verificador'])
        self.assertEqual(api.get(self.api_url).status_code, 200)
        self.assertEqual(api.post(self.api_url, self.datos, format='json').status_code, 403)
        self.compromiso.estado = Compromiso.Estado.REALIZADO
        self.compromiso.save(update_fields=['estado'])
        api.force_authenticate(self.usuarios['funcionario'])
        self.assertEqual(api.post(self.api_url, self.datos, format='json').status_code, 403)
        self.assertEqual(HistorialCompromiso.objects.filter(compromiso=self.compromiso, campo='avance').count(), 1)

    def test_api_lista_solamente_avances_y_observaciones(self):
        HistorialCompromiso.objects.create(compromiso=self.compromiso, campo='estado', valor_nuevo='Interno')
        HistorialCompromiso.objects.create(compromiso=self.compromiso, campo='observacion', valor_nuevo='Observación', realizado_por=self.usuarios['funcionario'])
        api = APIClient()
        api.force_authenticate(self.usuarios['funcionario'])
        respuesta = api.get(self.api_url)
        self.assertEqual(respuesta.data['count'], 1)
        self.assertEqual(respuesta.data['results'][0]['tipo'], 'observacion')
        self.assertEqual(respuesta.data['results'][0]['descripcion'], 'Observación')
