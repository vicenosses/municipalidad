from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from sgr.test_metas import DatosMetasMixin
from usuarios.backends import UsernameOrEmailBackend
from usuarios.mixins import obtener_rol
from usuarios.models import CodigoRecuperacion, Perfil


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RevisionRecuperacionTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user('revision-clave', password='ClaveAnterior2026!')
        self.codigo = CodigoRecuperacion.objects.create(usuario=self.usuario,
            codigo_hash=make_password('123456'), expira=timezone.now() + timedelta(minutes=10))
        self.sesion_verificada(self.client)

    def sesion_verificada(self, cliente):
        sesion = cliente.session
        sesion['recuperacion_id'] = self.codigo.pk
        sesion['recuperacion_ok'] = True
        sesion['recuperacion_pendiente'] = True
        sesion.save()

    def cambiar(self, cliente=None, clave='OtraClaveSegura2026!'):
        return (cliente or self.client).post(reverse('recuperacion_nueva'),
            {'new_password1': clave, 'new_password2': clave})

    def test_codigo_expira_despues_de_verificar_y_antes_de_guardar(self):
        CodigoRecuperacion.objects.filter(pk=self.codigo.pk).update(expira=timezone.now() - timedelta(seconds=1))
        self.assertRedirects(self.cambiar(), reverse('recuperacion_solicitar'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveAnterior2026!'))

    def test_codigo_usado_no_admite_get_ni_post_aunque_la_sesion_este_verificada(self):
        CodigoRecuperacion.objects.filter(pk=self.codigo.pk).update(usado=True)
        for metodo in ('get', 'post'):
            with self.subTest(metodo=metodo):
                respuesta = (self.client.get(reverse('recuperacion_nueva')) if metodo == 'get' else self.cambiar())
                self.assertRedirects(respuesta, reverse('recuperacion_solicitar'))

    def test_dos_sesiones_verificadas_no_reutilizan_el_mismo_codigo(self):
        otro = Client()
        self.sesion_verificada(otro)
        self.assertRedirects(self.cambiar(), reverse('login'))
        self.assertRedirects(self.cambiar(otro, 'ClaveReutilizada2026!'), reverse('recuperacion_solicitar'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('OtraClaveSegura2026!'))

    def test_expiracion_exacta_tambien_invalida_el_codigo(self):
        limite = timezone.now()
        CodigoRecuperacion.objects.filter(pk=self.codigo.pk).update(expira=limite)
        with patch('usuarios.auth_views.timezone.now', return_value=limite):
            self.assertRedirects(self.cambiar(), reverse('recuperacion_solicitar'))

    def test_perfil_desactivado_despues_de_verificar_no_cambia_contrasena(self):
        Perfil.objects.filter(usuario=self.usuario).update(activo=False)
        self.assertRedirects(self.cambiar(), reverse('recuperacion_solicitar'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveAnterior2026!'))

    def test_usuario_desactivado_despues_de_verificar_no_cambia_contrasena(self):
        get_user_model().objects.filter(pk=self.usuario.pk).update(is_active=False)
        self.assertRedirects(self.cambiar(), reverse('recuperacion_solicitar'))

    def test_cambio_valido_consume_codigo_y_limpia_sesion(self):
        self.assertRedirects(self.cambiar(), reverse('login'))
        self.codigo.refresh_from_db()
        self.assertTrue(self.codigo.usado)
        for clave in ('recuperacion_id', 'recuperacion_ok', 'recuperacion_pendiente'):
            self.assertNotIn(clave, self.client.session)

    def test_claves_invalidas_no_consumen_codigo(self):
        respuesta = self.client.post(reverse('recuperacion_nueva'),
            {'new_password1': 'ClaveDistinta2026!', 'new_password2': 'NoCoincide2026!'})
        self.assertEqual(respuesta.status_code, 200)
        self.codigo.refresh_from_db()
        self.assertFalse(self.codigo.usado)

    def test_fallo_al_guardar_clave_revierte_el_consumo_del_codigo(self):
        with patch('usuarios.auth_views.NuevaContrasenaForm.save', side_effect=RuntimeError('Fallo controlado')):
            with self.assertRaises(RuntimeError):
                self.cambiar()
        self.codigo.refresh_from_db()
        self.assertFalse(self.codigo.usado)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('ClaveAnterior2026!'))


class RevisionSesionesTests(DatosMetasMixin, TestCase):
    def test_backend_no_recupera_usuario_con_perfil_desactivado(self):
        usuario = self.usuarios['funcionario']
        Perfil.objects.filter(usuario=usuario).update(activo=False)
        self.assertIsNone(UsernameOrEmailBackend().get_user(usuario.pk))

    def test_sesion_existente_deja_de_autenticar_al_desactivar_perfil(self):
        self.client.force_login(self.usuarios['funcionario'])
        Perfil.objects.filter(usuario=self.usuarios['funcionario']).update(activo=False)
        self.assertRedirects(self.client.get(reverse('home')), reverse('login') + '?next=/',
                             fetch_redirect_response=False)

    def test_superusuario_con_perfil_desactivado_no_recupera_sesion(self):
        usuario = get_user_model().objects.create_superuser('super-revision', 'a@example.com', None)
        Perfil.objects.filter(usuario=usuario).update(activo=False)
        self.assertIsNone(UsernameOrEmailBackend().get_user(usuario.pk))
        usuario.refresh_from_db()
        self.assertIsNone(obtener_rol(usuario))

    def test_superusuario_inactivo_no_concede_rol_al_servicio(self):
        usuario = get_user_model()(is_superuser=True, is_active=False)
        self.assertIsNone(obtener_rol(usuario))

    def test_perfil_valido_conserva_sesion_y_superusuario_activo_su_rol(self):
        self.assertEqual(UsernameOrEmailBackend().get_user(self.usuarios['delegado'].pk), self.usuarios['delegado'])
        usuario = get_user_model().objects.create_superuser('super-valido-revision', 'b@example.com', None)
        self.assertEqual(obtener_rol(usuario), 'administrador')
