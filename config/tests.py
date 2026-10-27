from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import Resolver404, resolve, reverse

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.models import Evidencia
from usuarios.models import Delegacion, Perfil, Rol
from usuarios.mixins import obtener_permisos


User = get_user_model()


class HomeDashboardTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='clave-segura',
        )
        delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.delegacion = delegacion
        tipo = TipoAtencion.objects.create(codigo='TIP-1', nombre='Tipo')
        subatencion = SubAtencion.objects.create(
            codigo='SUB-1',
            nombre='Subatención',
            tipo=tipo,
        )
        AtencionCiudadana.objects.create(
            titulo='Actividad principal',
            fecha='2026-10-24',
            solicitante='Solicitante',
            tipo=tipo,
            subatencion=subatencion,
            descripcion='Descripción',
            delegacion=delegacion,
            responsable=self.usuario,
        )
        self.client.force_login(self.usuario)
        self.tipo = tipo
        self.subatencion = subatencion

    def test_dashboard_cuenta_atenciones_como_actividades(self):
        respuesta = self.client.get(reverse('home'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['total_actividades'], AtencionCiudadana.objects.count())
        self.assertContains(respuesta, 'Actividades')
        self.assertContains(respuesta, '>1</p>')

    def test_navegacion_de_actividades_apunta_a_atenciones(self):
        respuesta = self.client.get(reverse('home'))

        self.assertContains(
            respuesta,
            f'href="{reverse("atenciones:lista")}"',
        )

    def test_ruta_legacy_actividades_ya_no_se_resuelve(self):
        with self.assertRaises(Resolver404):
            resolve('/actividades/')

    def test_permisos_usan_atenciones_y_no_actividades_legacy(self):
        permisos = obtener_permisos(self.usuario)

        self.assertTrue(permisos['atenciones'])
        self.assertNotIn('actividades', permisos)

    def _crear_actividad(self, titulo, delegacion, responsable):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            solicitante=titulo,
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion=titulo,
            delegacion=delegacion,
            responsable=responsable,
        )

    def _crear_compromiso(self, titulo, delegacion, responsable):
        return Compromiso.objects.create(
            titulo=titulo,
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=responsable,
            delegacion=delegacion,
            estado=Compromiso.Estado.PENDIENTE,
        )

    def _crear_usuario_territorial(self, username, delegacion):
        rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        user = User.objects.create_user(username=username, password='clave-segura')
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = rol
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set([delegacion])
        return user

    def test_administrador_obtiene_metricas_globales(self):
        otra = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        actividad = self._crear_actividad('Actividad Norte', otra, self.usuario)
        compromiso = self._crear_compromiso('Compromiso Norte', otra, self.usuario)
        Evidencia.objects.create(
            atencion=actividad,
            archivo='evidencias/norte.png',
            subido_por=self.usuario,
        )

        respuesta = self.client.get(reverse('home'))

        self.assertEqual(respuesta.context['total_actividades'], 2)
        self.assertEqual(respuesta.context['compromisos_proximos'], 1)
        self.assertEqual(respuesta.context['evidencias_pendientes'], 1)

    def test_usuario_territorial_solo_ve_metricas_de_su_delegacion(self):
        otra = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        usuario = self._crear_usuario_territorial('func-territorial', self.delegacion)
        actividad_local = self._crear_actividad('Actividad Centro', self.delegacion, usuario)
        self._crear_actividad('Actividad Norte', otra, usuario)
        compromiso_local = self._crear_compromiso('Compromiso Centro', self.delegacion, usuario)
        self._crear_compromiso('Compromiso Norte', otra, usuario)
        Evidencia.objects.create(
            atencion=actividad_local,
            archivo='evidencias/centro.png',
            subido_por=usuario,
        )
        self.client.force_login(usuario)
        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion.pk
        session.save()

        respuesta = self.client.get(reverse('home'))

        self.assertEqual(respuesta.context['total_actividades'], 2)
        self.assertEqual(respuesta.context['compromisos_proximos'], 1)
        self.assertEqual(respuesta.context['evidencias_pendientes'], 1)
        self.assertEqual(
            respuesta.context['total_usuarios'],
            Perfil.objects.filter(activo=True, delegaciones=self.delegacion).count(),
        )

    def test_usuario_sin_delegacion_valida_ve_metricas_territoriales_en_cero(self):
        usuario = self._crear_usuario_territorial('func-sin-delegacion', self.delegacion)
        usuario.perfil.delegaciones.clear()
        self.client.force_login(usuario)
        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion.pk
        session.save()

        respuesta = self.client.get(reverse('home'))

        self.assertEqual(respuesta.context['total_actividades'], 0)
        self.assertEqual(respuesta.context['compromisos_proximos'], 0)
        self.assertEqual(respuesta.context['evidencias_pendientes'], 0)
        self.assertEqual(respuesta.context['total_usuarios'], 0)
