from django.contrib.auth.models import User
from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from usuarios.mixins import obtener_permisos, obtener_rol
from usuarios.models import Delegacion, Perfil, Rol
from usuarios.sesion import (
    DELEGACION_SESION,
    delegaciones_autorizadas,
    get_delegacion_activa,
    usuario_tiene_alcance_delegacion,
)


class AutomaticDelegacionCodeTests(TestCase):
    def test_creacion_por_post_ignora_codigo_enviado_y_edicion_lo_conserva(self):
        rol, _ = Rol.objects.get_or_create(
            codigo='coordinador',
            defaults={'nombre': 'Coordinador'},
        )
        rol.activo = True
        rol.save(update_fields=['activo'])
        user = User.objects.create_user(username='coord-codigos', password='clave-segura')
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = rol
        perfil.save()
        self.client.force_login(user)

        respuesta = self.client.post(
            reverse('usuarios:delegacion_crear'),
            {'codigo': 'HACK', 'nombre': 'Nueva delegación'},
        )

        self.assertEqual(respuesta.status_code, 302)
        delegacion = Delegacion.objects.get(nombre='Nueva delegación')
        self.assertRegex(delegacion.codigo, r'^DEL-\d{3,}$')
        self.assertNotEqual(delegacion.codigo, 'HACK')

        codigo_original = delegacion.codigo
        respuesta = self.client.post(
            reverse('usuarios:delegacion_editar', args=[delegacion.pk]),
            {'codigo': 'OTRO', 'nombre': 'Delegación editada'},
        )

        self.assertEqual(respuesta.status_code, 302)
        delegacion.refresh_from_db()
        self.assertEqual(delegacion.codigo, codigo_original)

    def test_codigos_delegacion_unicos_y_colision_secuencia_controlada(self):
        Delegacion.objects.bulk_create([
            Delegacion(pk=1, codigo='DEL-002', nombre='Histórica'),
        ])

        nueva = Delegacion.objects.create(nombre='Nueva')

        self.assertEqual(nueva.codigo, 'DEL-003')
        self.assertEqual(
            Delegacion.objects.filter(codigo=nueva.codigo).count(),
            1,
        )

    def test_codigo_historico_se_conserva_y_admin_lo_muestra_readonly(self):
        [historica] = Delegacion.objects.bulk_create([
            Delegacion(pk=44, codigo='CODIGO-HISTORICO', nombre='Histórica'),
        ])
        historica.nombre = 'Histórica editada'
        historica.save()
        historica.refresh_from_db()

        self.assertEqual(historica.codigo, 'CODIGO-HISTORICO')
        self.assertIn(
            'codigo',
            admin.site._registry[Delegacion].get_readonly_fields(
                RequestFactory().get('/admin/'),
                historica,
            ),
        )


class InfraestructuraRolesDelegacionTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.otra_delegacion = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        self.delegacion_inactiva = Delegacion.objects.create(
            codigo='DEL-3',
            nombre='Sur',
            activa=False,
        )
        self.roles = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': f'Prueba {codigo}'},
            )
            rol.activo = True
            rol.permisos = {}
            rol.save(update_fields=['activo', 'permisos'])
            self.roles[codigo] = rol
        self.request_factory = RequestFactory()

    def crear_usuario(self, username, codigo_rol, delegaciones=None, delegacion=None):
        user = User.objects.create_user(username=username, password='clave-segura')
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = self.roles[codigo_rol]
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set(delegaciones or [])
        user.perfil = perfil
        return user

    def crear_request(self, user, delegacion_id=None):
        request = self.request_factory.get('/')
        request.user = user
        request.session = {}
        if delegacion_id is not None:
            request.session[DELEGACION_SESION] = delegacion_id
        return request

    def test_rol_inactivo_no_concede_rol_ni_permisos_json(self):
        user = self.crear_usuario('inactivo', 'funcionario', [self.delegacion], self.delegacion)
        self.roles['funcionario'].permisos = {'usuarios': True}
        self.roles['funcionario'].activo = False
        self.roles['funcionario'].save()

        self.assertIsNone(obtener_rol(user))
        self.assertEqual(obtener_permisos(user), {})
        self.assertFalse(delegaciones_autorizadas(user).exists())

    def test_superusuario_conserva_rol_y_alcance_global(self):
        user = User.objects.create_superuser(
            username='superusuario',
            email='superusuario@example.com',
            password='clave-segura',
        )

        self.assertEqual(obtener_rol(user), 'administrador')
        self.assertTrue(usuario_tiene_alcance_delegacion(user, self.delegacion))
        self.assertFalse(usuario_tiene_alcance_delegacion(user, self.delegacion_inactiva))
        self.assertQuerySetEqual(
            delegaciones_autorizadas(user).order_by('pk'),
            [self.delegacion, self.otra_delegacion],
        )

    def test_administrador_normal_tiene_alcance_global_sobre_delegaciones_activas(self):
        user = self.crear_usuario('administrador', 'administrador')

        self.assertEqual(obtener_rol(user), 'administrador')
        self.assertTrue(usuario_tiene_alcance_delegacion(user, self.delegacion))
        self.assertTrue(usuario_tiene_alcance_delegacion(user, self.otra_delegacion))
        self.assertFalse(usuario_tiene_alcance_delegacion(user, self.delegacion_inactiva))
        self.assertEqual(
            set(delegaciones_autorizadas(user)),
            {self.delegacion, self.otra_delegacion},
        )

    def test_roles_delegacionales_no_obtienen_alcance_a_otra_delegacion(self):
        for codigo in ('delegado', 'coordinador', 'funcionario', 'verificador'):
            with self.subTest(rol=codigo):
                user = self.crear_usuario(
                    f'{codigo}-local',
                    codigo,
                    [self.delegacion],
                    self.delegacion,
                )

                self.assertTrue(usuario_tiene_alcance_delegacion(user, self.delegacion))
                self.assertFalse(usuario_tiene_alcance_delegacion(user, self.otra_delegacion))

    def test_delegacion_autorizada_activa_puede_ser_activa(self):
        user = self.crear_usuario('funcionario-activo', 'funcionario', [self.delegacion])
        request = self.crear_request(user, self.delegacion.pk)

        self.assertEqual(get_delegacion_activa(request), self.delegacion)

    def test_delegacion_inactiva_no_puede_quedar_activa(self):
        user = self.crear_usuario(
            'delegacion-inactiva',
            'funcionario',
            [self.delegacion_inactiva],
            self.delegacion_inactiva,
        )
        request = self.crear_request(user, self.delegacion_inactiva.pk)

        self.assertIsNone(get_delegacion_activa(request))
        self.assertNotIn(DELEGACION_SESION, request.session)

    def test_delegacion_no_autorizada_se_descarta_y_usa_una_autorizada(self):
        user = self.crear_usuario(
            'delegacion-ajena',
            'funcionario',
            [self.delegacion],
            self.delegacion,
        )
        request = self.crear_request(user, self.otra_delegacion.pk)

        self.assertEqual(get_delegacion_activa(request), self.delegacion)
        self.assertNotIn(DELEGACION_SESION, request.session)
        self.assertFalse(usuario_tiene_alcance_delegacion(user, self.otra_delegacion))

    def test_sesion_ya_no_autorizada_se_descarta(self):
        user = self.crear_usuario(
            'autorizacion-revocada',
            'coordinador',
            [self.delegacion, self.otra_delegacion],
            self.delegacion,
        )
        perfil = Perfil.objects.get(usuario=user)
        perfil.delegaciones.remove(self.otra_delegacion)
        request = self.crear_request(user, self.otra_delegacion.pk)

        self.assertEqual(get_delegacion_activa(request), self.delegacion)
        self.assertNotIn(DELEGACION_SESION, request.session)
        self.assertFalse(usuario_tiene_alcance_delegacion(user, self.otra_delegacion))

    def test_usuario_sin_delegaciones_validas_no_tiene_delegacion_activa(self):
        user = self.crear_usuario(
            'sin-delegaciones',
            'verificador',
            [self.delegacion_inactiva],
            self.otra_delegacion,
        )
        request = self.crear_request(user, self.otra_delegacion.pk)

        self.assertIsNone(get_delegacion_activa(request))
        self.assertNotIn(DELEGACION_SESION, request.session)
