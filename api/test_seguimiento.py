from django.test import TestCase
from rest_framework.test import APIClient
from auditoria.models import RegistroAuditoria
from gestion_social.models import GestionSocial, SeguimientoGestionSocial
from sgr.test_metas import DatosMetasMixin


class SeguimientoGestionAPITests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestion = GestionSocial.objects.create(titulo='Seguimiento', descripcion='Privado',
            delegacion=cls.a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'])
        cls.ajena = GestionSocial.objects.create(titulo='Otra', descripcion='Privado',
            delegacion=cls.b, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'])

    def setUp(self):
        self.api = APIClient()
        self.url = f'/api/v1/gestiones-sociales/{self.gestion.pk}/seguimientos/'
        self.datos = {'tipo':'avance', 'descripcion':'Se visitó a la persona solicitante.'}

    def test_responsable_crea_y_consulta_sin_falsificar_autor(self):
        self.api.force_authenticate(self.usuarios['funcionario'])
        respuesta = self.api.post(self.url, dict(self.datos, autor=self.usuarios['delegado'].pk,
                                               gestion=self.ajena.pk), format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        registro = SeguimientoGestionSocial.objects.get()
        self.assertEqual(registro.autor, self.usuarios['funcionario'])
        self.assertEqual(registro.gestion, self.gestion)
        self.assertEqual(respuesta.data['autor']['id'], self.usuarios['funcionario'].pk)
        self.assertIsNotNone(respuesta.data['creado_en'])
        listado = self.api.get(self.url)
        self.assertEqual(listado.status_code, 200)
        self.assertEqual(listado.data['count'], 1)
        self.assertEqual(listado.data['results'][0]['descripcion'], self.datos['descripcion'])
        auditoria = RegistroAuditoria.objects.get(accion='agregar_seguimiento_gestion', objeto_id=str(self.gestion.pk))
        self.assertNotIn(self.datos['descripcion'], auditoria.descripcion)

    def test_exige_autenticacion_y_restringe_otros_usuarios_y_delegaciones(self):
        self.assertEqual(self.api.get(self.url).status_code, 401)
        self.api.force_authenticate(self.usuarios['verificador'])
        self.assertEqual(self.api.get(self.url).status_code, 404)
        self.assertEqual(self.api.post(self.url, self.datos, format='json').status_code, 404)
        self.api.force_authenticate(self.usuarios['delegado'])
        self.assertEqual(self.api.get(self.url).status_code, 200)
        ajena = f'/api/v1/gestiones-sociales/{self.ajena.pk}/seguimientos/'
        self.assertEqual(self.api.get(ajena).status_code, 404)
        self.assertEqual(self.api.post(ajena, self.datos, format='json').status_code, 404)
        self.assertFalse(SeguimientoGestionSocial.objects.exists())

    def test_no_permite_escritura_en_gestiones_cerradas_o_inactivas(self):
        self.api.force_authenticate(self.usuarios['funcionario'])
        self.gestion.activo = False
        self.gestion.save(update_fields=['activo'])
        self.assertEqual(self.api.post(self.url, self.datos, format='json').status_code, 403)
        self.gestion.activo = True
        self.gestion.estado = GestionSocial.Estado.CERRADA
        self.gestion.save(update_fields=['activo', 'estado'])
        self.assertEqual(self.api.post(self.url, self.datos, format='json').status_code, 403)
        self.assertEqual(self.api.get(self.url).status_code, 200)
        self.assertFalse(SeguimientoGestionSocial.objects.exists())

    def test_rechaza_datos_invalidos_y_permite_consultar_como_creador_reasignado(self):
        self.api.force_authenticate(self.usuarios['funcionario'])
        for datos in ({'tipo':'avance', 'descripcion':'   '}, {'tipo':'inventado', 'descripcion':'Prueba'},
                      {'tipo':'avance', 'descripcion':'x'*4001}):
            with self.subTest(datos=datos.get('tipo')):
                self.assertEqual(self.api.post(self.url, datos, format='json').status_code, 400)
        self.gestion.responsable = self.usuarios['verificador']
        self.gestion.save(update_fields=['responsable'])
        self.assertEqual(self.api.get(self.url).status_code, 200)
        self.assertEqual(self.api.post(self.url, self.datos, format='json').status_code, 403)
        self.assertFalse(SeguimientoGestionSocial.objects.exists())

    def test_paginacion(self):
        SeguimientoGestionSocial.objects.bulk_create([
            SeguimientoGestionSocial(gestion=self.gestion, autor=self.usuarios['funcionario'],
                                      tipo='avance', descripcion=f'Nota {i}') for i in range(51)])
        self.api.force_authenticate(self.usuarios['funcionario'])
        respuesta = self.api.get(self.url)
        self.assertEqual(respuesta.data['count'], 51)
        self.assertEqual(len(respuesta.data['results']), 50)
        self.assertIsNotNone(respuesta.data['next'])
