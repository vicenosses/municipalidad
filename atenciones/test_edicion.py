from decimal import Decimal
from django.test import Client, TestCase
from django.urls import reverse
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from sgr.models import AporteIndicador
from sgr.test_aportes import DatosAportesMixin


class EdicionActividadTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.actividad.estado = AtencionCiudadana.Estado.EN_PROCESO
        self.actividad.save(update_fields=['estado'])
        self.url = reverse('atenciones:editar', args=[self.actividad.pk])
        self.datos = {'titulo':'Título corregido', 'fecha':self.actividad.fecha.isoformat(), 'solicitante':'Vecino corregido', 'territorio':'', 'descripcion':'Descripción corregida'}

    def test_autor_edita_y_audita_sin_modificar_campos_protegidos(self):
        self.entrar('funcionario')
        self.asociar()  # La fecha vinculada debe permanecer protegida.
        detalle = self.client.get(reverse('atenciones:detalle', args=[self.actividad.pk]))
        self.assertContains(detalle, self.url)
        fecha = self.actividad.fecha
        datos = dict(self.datos, fecha='2020-01-01', estado='cerrada', activo='false',
                     responsable=self.usuarios['verificador'].pk)
        respuesta = self.client.post(self.url, datos)
        self.assertEqual(respuesta.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.titulo, 'Título corregido')
        self.assertEqual(self.actividad.fecha, fecha)
        self.assertEqual(self.actividad.estado, AtencionCiudadana.Estado.EN_PROCESO)
        self.assertTrue(self.actividad.activo)
        self.assertEqual(self.actividad.responsable, self.usuarios['funcionario'])
        self.assertTrue(RegistroAuditoria.objects.filter(modelo='atenciones.AtencionCiudadana',
            objeto_id=str(self.actividad.pk), accion='editar_actividad').exists())

    def test_tercero_no_puede_editar_aunque_pertenezca_a_delegacion(self):
        self.entrar('verificador')
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 404)
        self.actividad.refresh_from_db()
        self.assertNotEqual(self.actividad.titulo, self.datos['titulo'])

    def test_no_permite_editar_cerrada_inactiva_o_con_aporte_aprobado(self):
        self.entrar('funcionario')
        self.actividad.activo = False
        self.actividad.save(update_fields=['activo'])
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 404)
        self.actividad.activo = True
        self.actividad.estado = AtencionCiudadana.Estado.CERRADA
        self.actividad.save(update_fields=['activo', 'estado'])
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 404)
        self.actividad.estado = AtencionCiudadana.Estado.EN_PROCESO
        self.actividad.save(update_fields=['estado'])
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte)
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 404)
        self.actividad.refresh_from_db()
        self.assertNotEqual(self.actividad.titulo, self.datos['titulo'])

    def test_admite_correccion_solicitada_y_deniega_aporte_rechazado(self):
        aporte = self.asociar()
        aporte = self.decidir(aporte, estado=AporteIndicador.Estado.REQUIERE_CORRECCION,
                             comentario='Corrija el dato', corregir_valor=True)
        self.entrar('funcionario')
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 302)
        aporte.estado = AporteIndicador.Estado.NO_CUMPLE
        aporte.comentario = 'Rechazado'
        aporte.save(update_fields=['estado', 'comentario'])
        self.assertEqual(self.client.post(self.url, self.datos).status_code, 404)

    def test_csrf_es_obligatorio(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['funcionario'])
        self.assertEqual(cliente.post(self.url, self.datos).status_code, 403)

    def test_puede_cambiar_fecha_y_territorio_de_su_delegacion(self):
        from usuarios.models import Territorio
        territorio = Territorio.objects.create(nombre='Sector local', delegacion=self.a)
        self.entrar('funcionario')
        datos = dict(self.datos, fecha='2026-10-22', territorio=str(territorio.pk))
        respuesta = self.client.post(self.url, datos)
        self.assertEqual(respuesta.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.fecha.isoformat(), '2026-10-22')
        self.assertEqual(self.actividad.territorio_id, territorio.pk)

    def test_no_permite_asignar_territorio_de_otra_delegacion(self):
        from usuarios.models import Territorio
        territorio = Territorio.objects.create(nombre='Sector ajeno', delegacion=self.b)
        self.entrar('funcionario')
        respuesta = self.client.post(self.url, dict(self.datos, territorio=str(territorio.pk)))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('territorio', respuesta.context['form'].errors)
        self.actividad.refresh_from_db()
        self.assertIsNone(self.actividad.territorio_id)

    def test_fecha_vinculada_a_compromiso_no_se_puede_manipular(self):
        from agenda.models import Compromiso
        from django.utils import timezone
        compromiso = Compromiso.objects.create(titulo='Seguimiento', fecha_hora=timezone.now(),
            responsable=self.usuarios['funcionario'], delegacion=self.a)
        compromiso.actividades.add(self.actividad)
        anterior = self.actividad.fecha
        self.entrar('funcionario')
        respuesta = self.client.post(self.url, dict(self.datos, fecha='2020-01-01'))
        self.assertEqual(respuesta.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.fecha, anterior)
