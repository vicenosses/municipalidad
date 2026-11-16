from django.test import Client, TestCase
from django.urls import reverse
from auditoria.models import RegistroAuditoria
from gestion_social.models import GestionSocial, SeguimientoGestionSocial
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class SeguimientoGestionTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ta = Territorio.objects.create(nombre='Centro', delegacion=cls.a)
        tb = Territorio.objects.create(nombre='Norte', delegacion=cls.b)
        cls.vecino_a = Vecino.objects.create(rut='98.765.432-1', nombres='Vecino', apellidos='A', territorio=ta)
        cls.vecino_b = Vecino.objects.create(rut='12.345.678-5', nombres='Vecino', apellidos='B', territorio=tb)
        cls.gestion = GestionSocial.objects.create(titulo='Gestión de prueba', descripcion='Datos reservados',
            delegacion=cls.a, vecino=cls.vecino_a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'])

    def test_responsable_registra_seguimiento_e_historial(self):
        self.entrar('funcionario')
        detalle = reverse('atenciones:gestion_social:detalle', args=[self.gestion.pk])
        url = reverse('atenciones:gestion_social:agregar_seguimiento', args=[self.gestion.pk])
        self.assertContains(self.client.get(detalle), 'Registrar seguimiento')
        respuesta = self.client.post(url, {'tipo':'avance', 'descripcion':'Se realizó visita de seguimiento.'})
        self.assertRedirects(respuesta, detalle)
        seguimiento = SeguimientoGestionSocial.objects.get(gestion=self.gestion)
        self.assertEqual(seguimiento.autor, self.usuarios['funcionario'])
        self.assertEqual(seguimiento.descripcion, 'Se realizó visita de seguimiento.')
        self.assertIsNotNone(seguimiento.creado_en)
        self.assertContains(self.client.get(detalle), 'Se realizó visita de seguimiento.')
        auditoria = RegistroAuditoria.objects.get(accion='agregar_seguimiento_gestion', objeto_id=str(self.gestion.pk))
        self.assertNotIn(seguimiento.descripcion, auditoria.descripcion)

    def test_impide_tercero_inactivo_y_cerrado(self):
        url = reverse('atenciones:gestion_social:agregar_seguimiento', args=[self.gestion.pk])
        datos = {'tipo':'observacion', 'descripcion':'Prueba'}
        self.entrar('verificador')
        self.assertEqual(self.client.post(url, datos).status_code, 404)
        self.entrar('funcionario')
        self.gestion.activo = False
        self.gestion.save(update_fields=['activo'])
        self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.gestion.activo = True
        self.gestion.estado = GestionSocial.Estado.CERRADA
        self.gestion.fecha_cierre = self.gestion.fecha_ingreso
        self.gestion.save(update_fields=['activo', 'estado', 'fecha_cierre'])
        self.assertEqual(self.client.post(url, datos).status_code, 403)
        self.assertFalse(SeguimientoGestionSocial.objects.exists())

    def test_delegado_puede_seguir_gestion_y_no_otras_delegaciones(self):
        ajena = GestionSocial.objects.create(titulo='Otra', descripcion='Privado', delegacion=self.b, vecino=self.vecino_b,
            responsable=self.usuarios['funcionario'])
        self.entrar('delegado')
        datos = {'tipo':'observacion', 'descripcion':'Seguimiento del equipo'}
        self.assertEqual(self.client.post(reverse('atenciones:gestion_social:agregar_seguimiento', args=[self.gestion.pk]), datos).status_code, 302)
        self.assertEqual(self.client.post(reverse('atenciones:gestion_social:agregar_seguimiento', args=[ajena.pk]), datos).status_code, 404)

    def test_valida_datos_y_csrf(self):
        url = reverse('atenciones:gestion_social:agregar_seguimiento', args=[self.gestion.pk])
        self.entrar('funcionario')
        respuesta = self.client.post(url, {'tipo':'avance', 'descripcion':'   '})
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(SeguimientoGestionSocial.objects.exists())
        self.assertIn('descripcion', respuesta.context['form_seguimiento'].errors)
        self.assertContains(respuesta, 'id_descripcion', status_code=400)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['funcionario'])
        self.assertEqual(cliente.post(url, {'tipo':'avance', 'descripcion':'Prueba'}).status_code, 403)

