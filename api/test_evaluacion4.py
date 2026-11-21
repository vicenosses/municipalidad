from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from atenciones.models import AtencionCiudadana
from catalogos.models import TipoAtencion, SubAtencion
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class ApiEvaluacionTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tipo = TipoAtencion.objects.create(codigo='TEST', nombre='Tipo')
        cls.sub = SubAtencion.objects.create(nombre='Consulta', tipo=cls.tipo)
        cls.actividad = AtencionCiudadana.objects.create(
            titulo='Atención', fecha='2026-11-10', solicitante='Vecino ficticio',
            descripcion='Prueba', tipo=cls.tipo, subatencion=cls.sub,
            delegacion=cls.a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'])

    def setUp(self):
        self.api = APIClient()

    def test_mantenedores_crud_y_restricciones(self):
        self.assertEqual(self.api.get('/api/v1/tipos-atencion/').status_code, 401)
        self.api.force_authenticate(self.usuarios['funcionario'])
        self.assertEqual(self.api.post('/api/v1/tipos-atencion/', {'codigo':'T2', 'nombre':'Nuevo'}, format='json').status_code, 403)
        self.api.force_authenticate(self.usuarios['administrador'])
        tipo = self.api.post('/api/v1/tipos-atencion/', {'codigo':'T2', 'nombre':'Nuevo', 'activo':True}, format='json')
        self.assertEqual(tipo.status_code, 201, tipo.data)
        pk = tipo.data['id']
        url = f'/api/v1/tipos-atencion/{pk}/'
        self.assertEqual(self.api.get(url).status_code, 200)
        editado = self.api.put(url, {'codigo':'T2', 'nombre':'Actualizado', 'activo':True}, format='json')
        self.assertEqual(editado.status_code, 200, editado.data)
        sub = self.api.post('/api/v1/subatenciones/', {'nombre':'Nueva', 'tipo':pk, 'activo':True}, format='json')
        self.assertEqual(sub.status_code, 201, sub.data)
        sub_url = f"/api/v1/subatenciones/{sub.data['id']}/"
        self.assertEqual(self.api.get(sub_url).status_code, 200)
        self.assertEqual(self.api.put(sub_url, {'nombre':'Editada', 'tipo':pk, 'activo':True}, format='json').status_code, 200)
        self.assertEqual(self.api.delete(url).status_code, 400)
        self.assertEqual(self.api.delete(sub_url).status_code, 204)
        self.assertEqual(self.api.delete(url).status_code, 204)

    def test_delegado_no_modifica_catalogo_global_ni_otra_delegacion(self):
        self.api.force_authenticate(self.usuarios['delegado'])
        self.assertEqual(self.api.put(f'/api/v1/tipos-atencion/{self.tipo.pk}/', {'codigo':'TEST', 'nombre':'Cambio'}, format='json').status_code, 404)
        respuesta = self.api.post('/api/v1/tipos-atencion/', {'codigo':'LOCAL', 'nombre':'Local', 'delegacion':self.b.pk}, format='json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(TipoAtencion.objects.filter(codigo='LOCAL').exists())

    def test_se_preserva_estado_y_alcance_al_actualizar_catalogo(self):
        self.api.force_authenticate(self.usuarios['administrador'])
        creado = self.api.post('/api/v1/tipos-atencion/', {'codigo': 'TERR', 'nombre': 'Territorial', 'delegacion': self.a.pk}, format='json')
        self.assertEqual(creado.status_code, 201, creado.data)
        self.assertTrue(creado.data['activo'])
        url = f"/api/v1/tipos-atencion/{creado.data['id']}/"
        editado = self.api.put(url, {'codigo': 'TERR', 'nombre': 'Territorial editado'}, format='json')
        self.assertEqual(editado.status_code, 200, editado.data)
        self.assertTrue(editado.data['activo'])
        self.assertEqual(editado.data['delegacion'], self.a.pk)

    def test_actividad_solo_autor_edita_y_no_se_elimina_si_relacionada(self):
        url = f'/api/v1/actividades/{self.actividad.pk}/'
        self.api.force_authenticate(self.usuarios['funcionario'])
        cambio = self.api.patch(url, {'titulo':'Atención actualizada'}, format='json')
        self.assertEqual(cambio.status_code, 200, cambio.data)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.titulo, 'Atención actualizada')
        self.assertEqual(self.api.patch(url, {'estado':'cerrada'}, format='json').status_code, 400)
        self.assertEqual(self.api.delete(url).status_code, 403)
        self.api.force_authenticate(self.usuarios['verificador'])
        self.assertEqual(self.api.patch(url, {'titulo':'Ajena'}, format='json').status_code, 403)

    def test_crear_actividad_con_catalogos_y_rechazar_periodo_cerrado(self):
        self.api.force_authenticate(self.usuarios['funcionario'])
        datos = {'titulo': 'Visita vecinal', 'fecha': '2026-11-10', 'solicitante': 'Vecino ficticio',
                 'tipo': self.tipo.pk, 'subatencion': self.sub.pk, 'descripcion': 'Visita realizada.'}
        respuesta = self.api.post('/api/v1/actividades/', datos, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        registro = AtencionCiudadana.objects.get(pk=respuesta.data['id'])
        self.assertEqual((registro.tipo_id, registro.subatencion_id), (self.tipo.pk, self.sub.pk))
        type(self.periodo).objects.filter(pk=self.periodo.pk).update(cerrado=True)
        datos['titulo'] = 'Registro no permitido'
        respuesta = self.api.post('/api/v1/actividades/', datos, format='json')
        self.assertEqual(respuesta.status_code, 400, respuesta.data)
        self.assertFalse(AtencionCiudadana.objects.filter(titulo='Registro no permitido').exists())

    def test_administrador_puede_eliminar_actividad_libre(self):
        url = f'/api/v1/actividades/{self.actividad.pk}/'
        self.api.force_authenticate(self.usuarios['administrador'])
        self.assertEqual(self.api.delete(url).status_code, 204)
        self.assertFalse(AtencionCiudadana.objects.filter(pk=self.actividad.pk).exists())

    def test_datos_personales_se_muestran_segun_rol(self):
        territorio = Territorio.objects.create(nombre='Sector de prueba', delegacion=self.a)
        vecino = Vecino.objects.create(rut='12.345.678-5', nombres='Persona', apellidos='Prueba',
            telefono='111111', correo='prueba@example.test', direccion='Dirección ficticia', territorio=territorio)
        self.api.force_authenticate(self.usuarios['funcionario'])
        respuesta = self.api.get(f'/api/v1/vecinos/{vecino.pk}/', {'q': 'Persona'})
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('telefono', respuesta.data)
        self.assertNotIn('correo', respuesta.data)
        self.assertNotIn('direccion', respuesta.data)
        self.api.force_authenticate(self.usuarios['administrador'])
        respuesta = self.api.get(f'/api/v1/vecinos/{vecino.pk}/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data['telefono'], '111111')
        self.assertEqual(respuesta.data['correo'], 'prueba@example.test')
        self.assertEqual(self.api.get(f'/api/v1/actividades/{self.actividad.pk}/').data['solicitante'], 'Vecino ficticio')

    def test_perfil_oculta_correo_privado_y_api_siempre_responde_json(self):
        funcionario = self.usuarios['funcionario']
        funcionario.email = 'funcionario@example.test'
        funcionario.save(update_fields=['email'])
        self.api.force_authenticate(funcionario)
        respuesta = self.api.get('/api/v1/yo/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertNotIn('email', respuesta.data)
        html = self.api.get('/api/v1/yo/', HTTP_ACCEPT='text/html')
        self.assertEqual(html.status_code, 406)
        self.assertEqual(html['Content-Type'], 'application/json')

        administrador = self.usuarios['administrador']
        administrador.email = 'administrador@example.test'
        administrador.save(update_fields=['email'])
        self.api.force_authenticate(administrador)
        respuesta = self.api.get('/api/v1/yo/')
        self.assertEqual(respuesta.data['email'], 'administrador@example.test')

    def test_documentacion_y_esquema_incluyen_jwt_y_operaciones(self):
        respuesta = self.client.get('/api/documentacion/')
        self.assertEqual(respuesta.status_code, 200)
        esquema = self.client.get('/api/esquema/', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(esquema.status_code, 200)
        contenido = esquema.json()
        self.assertIn('jwtAuth', contenido['components']['securitySchemes'])
        self.assertIn('post', contenido['paths']['/api/v1/tipos-atencion/'])
        self.assertIn('put', contenido['paths']['/api/v1/subatenciones/{id}/'])
        self.assertIn('delete', contenido['paths']['/api/v1/actividades/{id}/'])

    def test_jwt_obtencion_acceso_renovacion_y_rotacion(self):
        usuario = self.usuarios['funcionario']
        usuario.set_password('Contraseña-segura-123!')
        usuario.save(update_fields=['password'])
        token = self.api.post('/api/v1/auth/token/', {'username': usuario.username, 'password': 'Contraseña-segura-123!'}, format='json')
        self.assertEqual(token.status_code, 200, token.data)
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
        self.assertEqual(self.api.get('/api/v1/actividades/').status_code, 200)
        self.api.credentials()
        renovado = self.api.post('/api/v1/auth/token/refresh/', {'refresh': token.data['refresh']}, format='json')
        self.assertEqual(renovado.status_code, 200, renovado.data)
        self.assertIn('access', renovado.data)
        self.assertEqual(self.api.post('/api/v1/auth/token/refresh/', {'refresh': token.data['refresh']}, format='json').status_code, 401)

    @override_settings(DEBUG=False)
    def test_ruta_inexistente_entrega_json(self):
        respuesta = self.client.get('/api/v1/no-existe/')
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(respuesta.json(), {'detail': 'Recurso no encontrado.'})
