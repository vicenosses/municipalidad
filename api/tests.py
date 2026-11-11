from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from gestion_social.models import GestionSocial
from auditoria.models import RegistroAuditoria
from usuarios.models import Delegacion, Rol, Territorio, Vecino


class APIPruebas(APITestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(nombre='Delegación Centro')
        self.otra_delegacion = Delegacion.objects.create(nombre='Delegación Norte')
        self.territorio = Territorio.objects.create(
            nombre='Centro', delegacion=self.delegacion,
        )
        self.vecino = Vecino.objects.create(
            rut='98.765.432-1',
            nombres='Vecino',
            apellidos='De prueba',
            territorio=self.territorio,
        )
        self.usuario = self._crear_usuario('funcionario', self.delegacion, 'funcionario')
        self.otro_usuario = self._crear_usuario('funcionario', self.otra_delegacion, 'otro')
        self.tipo = TipoAtencion.objects.create(codigo='GEN', nombre='General')
        self.subatencion = SubAtencion.objects.create(
            codigo='SUB', nombre='Consulta', tipo=self.tipo,
        )

    def _crear_usuario(self, codigo_rol, delegacion, username):
        usuario = User.objects.create_user(
            username=username,
            password='Contrasena_segura_123!',
            first_name='Nombre',
            last_name='Apellido',
            email=f'{username}@example.test',
        )
        rol, _ = Rol.objects.get_or_create(
            codigo=codigo_rol,
            defaults={'nombre': codigo_rol.title()},
        )
        perfil = usuario.perfil
        perfil.rol = rol
        perfil.delegacion = delegacion
        perfil.cargo = 'Funcionario municipal'
        perfil.save()
        perfil.delegaciones.add(delegacion)
        return usuario

    def _actividad(self, delegacion, responsable, titulo='Actividad'):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-01',
            solicitante='Vecino de prueba',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Detalle interno',
            delegacion=delegacion,
            responsable=responsable,
            creado_por=responsable,
            territorio=self.territorio if delegacion == self.delegacion else None,
        )

    def test_api_exige_autenticacion_y_entrega_token(self):
        respuesta = self.client.get('/api/v1/actividades/')
        self.assertEqual(respuesta.status_code, 401)

        respuesta = self.client.post('/api/v1/auth/token/', {
            'username': self.usuario.username,
            'password': 'Contrasena_segura_123!',
        })
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('access', respuesta.data)
        self.assertIn('refresh', respuesta.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {respuesta.data['access']}")
        perfil = self.client.get('/api/v1/yo/')
        self.assertEqual(perfil.status_code, 200)
        self.assertEqual(perfil.data['rol'], 'funcionario')

    def test_listados_respetan_delegacion_y_minimizan_datos_personales(self):
        propia = self._actividad(self.delegacion, self.usuario, 'Visible')
        ajena = self._actividad(self.otra_delegacion, self.otro_usuario, 'No visible')
        self.client.force_authenticate(self.usuario)

        respuesta = self.client.get('/api/v1/actividades/')
        self.assertEqual(respuesta.status_code, 200)
        ids = {fila['id'] for fila in respuesta.data['results']}
        self.assertIn(propia.pk, ids)
        self.assertNotIn(ajena.pk, ids)
        self.assertNotIn('solicitante', respuesta.data['results'][0])
        self.assertIsNone(respuesta.data['results'][0]['descripcion'])

        vecino = Vecino.objects.create(
            rut='12.345.678-5',
            nombres='María José',
            apellidos='Pérez Soto',
            telefono='56912345678',
            correo='vecina@example.test',
            direccion='Dirección reservada',
            territorio=self.territorio,
        )
        vecinos = self.client.get('/api/v1/vecinos/', {'q': '123456785'})
        self.assertEqual(vecinos.status_code, 200)
        self.assertEqual(vecinos.data['results'][0]['id'], vecino.pk)
        self.assertEqual(vecinos.data['results'][0]['rut'], '****.678-5')
        self.assertNotIn('telefono', vecinos.data['results'][0])
        self.assertNotIn('direccion', vecinos.data['results'][0])

    def test_crea_gestion_social_con_codigo_y_auditoria_sin_detalle_sensible(self):
        self.client.force_authenticate(self.usuario)
        respuesta = self.client.post('/api/v1/gestiones-sociales/', {
            'titulo': 'Orientación vecinal',
            'tipo': 'orientacion',
            'descripcion': 'Antecedentes privados de la atención.',
            'delegacion': self.delegacion.pk,
            'territorio': self.territorio.pk,
            'vecino': self.vecino.pk,
            'fecha_ingreso': '2026-10-01',
            'ingresa_al_tubo': True,
        }, format='json')
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        gestion = GestionSocial.objects.get(pk=respuesta.data['id'])
        self.assertTrue(gestion.codigo.startswith('GES-'))
        self.assertEqual(gestion.responsable_id, self.usuario.pk)
        self.assertTrue(gestion.ingresa_al_tubo)
        self.assertEqual(respuesta.data['descripcion'], gestion.descripcion)
        self.assertEqual(gestion._meta.label, 'gestion_social.GestionSocial')
        auditoria = RegistroAuditoria.objects.get(modelo='gestion_social.GestionSocial')
        self.assertIn(gestion.codigo, auditoria.descripcion)
        self.assertNotIn(gestion.descripcion, auditoria.descripcion)

    def test_gestion_social_no_expone_contenido_en_listado_y_no_se_elimina(self):
        gestion = GestionSocial.objects.create(
            titulo='Apoyo',
            descripcion='Información privada.',
            delegacion=self.delegacion,
            territorio=self.territorio,
            vecino=self.vecino,
            responsable=self.usuario,
            creado_por=self.usuario,
        )
        self.client.force_authenticate(self.usuario)
        listado = self.client.get('/api/v1/gestiones-sociales/')
        self.assertEqual(listado.status_code, 200)
        self.assertNotIn('descripcion', listado.data['results'][0])
        eliminacion = self.client.delete(f'/api/v1/gestiones-sociales/{gestion.pk}/')
        self.assertEqual(eliminacion.status_code, 405)
        self.assertTrue(GestionSocial.objects.filter(pk=gestion.pk).exists())

    def test_cartas_hitos_transiciones_y_tubo_unificado(self):
        self.client.force_authenticate(self.usuario)
        carta = self.client.post('/api/v1/cartas/', {
            'asunto': 'Solicitud de apoyo',
            'contenido': 'Contenido confidencial de la carta.',
            'delegacion': self.delegacion.pk,
            'territorio': self.territorio.pk,
            'fecha_ingreso': '2026-10-01',
            'ingresa_al_tubo': True,
        }, format='json')
        self.assertEqual(carta.status_code, 201, carta.data)
        carta_listado = self.client.get('/api/v1/cartas/')
        self.assertEqual(carta_listado.status_code, 200)
        self.assertNotIn('contenido', carta_listado.data['results'][0])
        carta_id = carta.data['id']
        en_proceso = self.client.post(
            f'/api/v1/cartas/{carta_id}/estado/',
            {'estado': 'en_proceso'},
            format='json',
        )
        self.assertEqual(en_proceso.status_code, 200, en_proceso.data)
        respondida = self.client.post(
            f'/api/v1/cartas/{carta_id}/estado/',
            {'estado': 'respondida', 'respuesta': 'Respuesta municipal.'},
            format='json',
        )
        self.assertEqual(respondida.status_code, 200, respondida.data)
        self.assertEqual(respondida.data['estado'], 'respondida')

        actividad = self._actividad(self.delegacion, self.usuario)
        hito = self.client.post('/api/v1/hitos/', {
            'titulo': 'Revisar avance',
            'actividad': actividad.pk,
            'fecha_programada': '2026-10-02',
        }, format='json')
        self.assertEqual(hito.status_code, 201, hito.data)
        en_progreso = self.client.post(
            f"/api/v1/hitos/{hito.data['id']}/estado/",
            {'estado': 'en_proceso'},
            format='json',
        )
        self.assertEqual(en_progreso.status_code, 200, en_progreso.data)
        self.assertEqual(en_progreso.data['estado'], 'en_proceso')

        tubo = self.client.get('/api/v1/tubo/')
        self.assertEqual(tubo.status_code, 200)
        registros = tubo.data['results']
        self.assertTrue(any(item['tipo'] == 'carta' for item in registros))
        self.assertNotIn('contenido', registros[0])

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_recuperacion_no_revela_si_existe_la_cuenta(self):
        conocido = self.client.post('/api/v1/auth/recuperacion/', {
            'identificador': self.usuario.email,
        }, format='json')
        desconocido = self.client.post('/api/v1/auth/recuperacion/', {
            'identificador': 'no-existe@example.test',
        }, format='json')
        self.assertEqual(conocido.status_code, 202)
        self.assertEqual(desconocido.status_code, 202)
        self.assertEqual(conocido.data, desconocido.data)
