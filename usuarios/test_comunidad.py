from django.test import TestCase
from django.urls import reverse

from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino, JuntaVecinos, ParticipacionJunta


class ComunidadTests(DatosMetasMixin, TestCase):
    def setUp(self):
        self.territorio_a = Territorio.objects.create(nombre='Centro', delegacion=self.a)
        self.territorio_b = Territorio.objects.create(nombre='Norte', delegacion=self.b)
        self.entrar('administrador')

    def test_registro_vecino_valida_y_normaliza_rut(self):
        url = reverse('usuarios:comunidad_crear', args=['vecinos'])
        datos = {'rut': '12345678-5', 'nombres': 'Persona', 'apellidos': 'Prueba',
                 'territorio': self.territorio_a.pk, 'activo': 'on'}
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        self.assertEqual(Vecino.objects.get().rut, '12.345.678-5')
        datos['rut'] = '12345678-0'
        self.assertEqual(self.client.post(url, datos).status_code, 400)

    def test_participacion_no_mezcla_delegaciones(self):
        vecino = Vecino.objects.create(rut='12.345.678-5', nombres='Persona', apellidos='Prueba', territorio=self.territorio_a)
        junta = JuntaVecinos.objects.create(nombre='Junta', territorio=self.territorio_b)
        url = reverse('usuarios:comunidad_crear', args=['participaciones'])
        respuesta = self.client.post(url, {'vecino': vecino.pk, 'junta': junta.pk, 'activo': 'on'})
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(ParticipacionJunta.objects.exists())

    def test_delegado_no_ve_vecinos_ajenos(self):
        Vecino.objects.create(rut='12.345.678-5', nombres='Visible', apellidos='Prueba', territorio=self.territorio_a)
        Vecino.objects.create(rut='11.111.111-1', nombres='Privado', apellidos='Prueba', territorio=self.territorio_b)
        self.entrar('delegado')
        respuesta = self.client.get(reverse('usuarios:comunidad_lista', args=['vecinos']))
        self.assertContains(respuesta, 'Visible')
        self.assertNotContains(respuesta, 'Privado')
        self.assertEqual(self.client.get(reverse('usuarios:comunidad_crear', args=['vecinos'])).status_code, 403)

    def test_cambio_de_delegacion_no_rompe_participaciones(self):
        vecino = Vecino.objects.create(rut='12.345.678-5', nombres='Persona', apellidos='Prueba', territorio=self.territorio_a)
        junta = JuntaVecinos.objects.create(nombre='Junta', territorio=self.territorio_a)
        ParticipacionJunta.objects.create(vecino=vecino, junta=junta)
        respuesta = self.client.post(reverse('usuarios:comunidad_editar', args=['vecinos', vecino.pk]),
            {'rut': vecino.rut, 'nombres': vecino.nombres, 'apellidos': vecino.apellidos,
             'territorio': self.territorio_b.pk, 'activo': 'on'})
        self.assertEqual(respuesta.status_code, 400)
        vecino.refresh_from_db()
        self.assertEqual(vecino.territorio, self.territorio_a)

    def test_estado_y_detalle_respetan_delegacion_y_permisos(self):
        vecino = Vecino.objects.create(rut='12.345.678-5', nombres='Visible', apellidos='Prueba', territorio=self.territorio_a)
        estado = reverse('usuarios:comunidad_estado', args=['vecinos', vecino.pk])
        detalle = reverse('usuarios:comunidad_detalle', args=['vecinos', vecino.pk])
        self.assertContains(self.client.get(detalle), vecino.rut)
        self.entrar('delegado')
        self.assertEqual(self.client.post(estado, {'activo': 'false'}).status_code, 403)
        self.entrar('administrador')
        self.assertEqual(self.client.post(estado, {'activo': 'false'}).status_code, 302)
        vecino.refresh_from_db()
        self.assertFalse(vecino.activo)
        self.assertEqual(self.client.post(estado, {'activo': 'true'}).status_code, 302)
        vecino.refresh_from_db()
        self.assertTrue(vecino.activo)

    def test_busqueda_paginas_y_orden_de_estado(self):
        for n in range(27):
            Vecino.objects.create(rut=f'prueba-{n}', nombres='Persona', apellidos=f'{n:02}',
                                  territorio=self.territorio_a, activo=n != 0)
        Vecino.objects.create(rut='otra', nombres='Distinta', apellidos='Prueba', territorio=self.territorio_a)
        url = reverse('usuarios:comunidad_lista', args=['vecinos'])
        respuesta = self.client.get(url, {'q': 'Persona'})
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 27)
        self.assertEqual(len(respuesta.context['registros']), 25)
        self.assertContains(respuesta, 'q=Persona&amp;page=2')
        siguiente = self.client.get(url, {'q': 'Persona', 'page': 2})
        self.assertEqual(len(siguiente.context['registros']), 2)
        self.assertFalse(list(siguiente.context['registros'])[-1].activo)

    def test_menu_permanece_abierto_en_comunidad_y_cerrado_en_inicio(self):
        for tipo in ('vecinos', 'juntas', 'participaciones'):
            with self.subTest(tipo=tipo):
                respuesta = self.client.get(reverse('usuarios:comunidad_lista', args=[tipo]))
                self.assertTrue(respuesta.context['sesion_comunidad_activa'])
                self.assertContains(respuesta, 'dropdown-menu show')
                self.assertContains(respuesta, 'hide.bs.dropdown')
        respuesta = self.client.get(reverse('usuarios:comunidad_crear', args=['vecinos']))
        self.assertTrue(respuesta.context['sesion_comunidad_activa'])
        respuesta = self.client.get(reverse('home'))
        self.assertFalse(respuesta.context['sesion_comunidad_activa'])
        self.assertNotContains(respuesta, 'hide.bs.dropdown')

    def test_menu_comunidad_visible_solo_a_roles_con_acceso(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            with self.subTest(rol=rol):
                self.entrar(rol)
                respuesta = self.client.get(reverse('home'))
                self.assertContains(respuesta, 'menuComunidad')
                self.assertContains(respuesta, reverse('usuarios:comunidad_lista', args=['vecinos']))
                self.assertContains(respuesta, reverse('usuarios:comunidad_lista', args=['juntas']))
        self.entrar('funcionario')
        self.assertNotContains(self.client.get(reverse('home')), 'menuComunidad')
