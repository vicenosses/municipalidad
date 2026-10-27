from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import RegistroAuditoria
from sgr.forms import PeriodoForm
from sgr.models import Periodo
from usuarios.models import Delegacion, Perfil, Rol


class PeriodoModeloTests(TestCase):
    def periodo(self, **kwargs):
        datos = dict(nombre='Primer semestre', fecha_inicio=date(2026, 1, 1),
                     fecha_fin=date(2026, 6, 30))
        datos.update(kwargs)
        return Periodo.objects.create(**datos)

    def test_creacion_valida_y_normalizacion(self):
        periodo = self.periodo(nombre='  Primer   semestre  ')
        self.assertEqual(periodo.nombre, 'Primer semestre')
        self.assertTrue(periodo.activo)
        self.assertIsNotNone(periodo.creado_en)
        self.assertIsNotNone(periodo.actualizado_en)

    def test_nombre_blanco_y_fechas_invertidas_rechazados(self):
        for datos in ({'nombre': '   '}, {'fecha_fin': date(2025, 12, 31)}):
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                self.periodo(**datos)

    def test_superposicion_inclusiva_y_periodo_contenido(self):
        self.periodo()
        for inicio, fin in ((date(2026, 6, 30), date(2026, 12, 31)),
                            (date(2026, 2, 1), date(2026, 3, 1)),
                            (date(2025, 1, 1), date(2027, 1, 1))):
            with self.subTest(inicio=inicio), self.assertRaises(ValidationError):
                self.periodo(nombre='Otro', fecha_inicio=inicio, fecha_fin=fin)

    def test_periodos_contiguos_y_de_un_dia_validos(self):
        self.periodo()
        self.periodo(nombre='Día', fecha_inicio=date(2026, 7, 1), fecha_fin=date(2026, 7, 1))
        self.assertEqual(Periodo.objects.count(), 2)

    def test_inactivos_no_bloquean_fechas_ni_nombres(self):
        self.periodo(activo=False)
        self.periodo()
        self.periodo(activo=False)
        self.assertEqual(Periodo.objects.count(), 3)

    def test_nombre_activo_duplicado_independiente_de_fechas(self):
        self.periodo(nombre='Período común')
        with self.assertRaises(ValidationError):
            self.periodo(nombre='  PERÍODO COMÚN ', fecha_inicio=date(2027, 1, 1),
                         fecha_fin=date(2027, 6, 30))

    def test_edicion_excluye_objeto_y_revalida_conflictos(self):
        periodo = self.periodo()
        periodo.nombre = 'Editado'
        periodo.save()
        self.periodo(nombre='Segundo', fecha_inicio=date(2026, 7, 1), fecha_fin=date(2026, 12, 31))
        periodo.fecha_fin = date(2026, 7, 1)
        with self.assertRaises(ValidationError):
            periodo.save()

    def test_reactivacion_rechaza_fechas_y_nombre_en_conflicto(self):
        self.periodo()
        for datos in ({'nombre': 'Otro'}, {'fecha_inicio': date(2027, 1, 1),
                                          'fecha_fin': date(2027, 6, 30)}):
            periodo = self.periodo(activo=False, **datos)
            periodo.activo = True
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                periodo.save()
            periodo.refresh_from_db()
            self.assertFalse(periodo.activo)

    def test_formulario_valida_nombre_fechas_y_conflictos(self):
        self.periodo()
        for datos in (
            {'nombre': '  ', 'fecha_inicio': '2027-01-01', 'fecha_fin': '2027-12-31'},
            {'nombre': 'Otro', 'fecha_inicio': '2027-12-31', 'fecha_fin': '2027-01-01'},
            {'nombre': 'Otro', 'fecha_inicio': '2026-06-01', 'fecha_fin': '2026-12-31'},
            {'nombre': 'primer semestre', 'fecha_inicio': '2027-01-01', 'fecha_fin': '2027-12-31'},
            {'nombre': 'Otro', 'fecha_inicio': 'ayer', 'fecha_fin': ''},
        ):
            with self.subTest(datos=datos):
                self.assertFalse(PeriodoForm(data=datos).is_valid())

    def test_conserva_periodo_al_eliminar_creador(self):
        usuario = get_user_model().objects.create_user(username='creador')
        periodo = self.periodo(creado_por=usuario)
        usuario.delete()
        periodo.refresh_from_db()
        self.assertIsNone(periodo.creado_por)


class PeriodoVistasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuarios = {}
        delegacion = Delegacion.objects.create(codigo='S9', nombre='Delegación SGR')
        for codigo in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            usuario = get_user_model().objects.create_user(username=codigo)
            rol, _ = Rol.objects.get_or_create(codigo=codigo, defaults={'nombre': codigo})
            Perfil.objects.filter(usuario=usuario).update(rol=rol, delegacion=delegacion)
            usuario.refresh_from_db()
            usuario.perfil.delegaciones.add(delegacion)
            cls.usuarios[codigo] = usuario
        cls.periodo = Periodo.objects.create(nombre='Primer semestre', fecha_inicio='2026-01-01',
                                             fecha_fin='2026-06-30')

    def url(self, nombre, objeto=True):
        return reverse(f'sgr:periodo_{nombre}', args=[self.periodo.pk] if objeto else [])

    def entrar(self, rol):
        self.client.force_login(self.usuarios[rol])

    def datos(self, **kwargs):
        datos = {'nombre': 'Segundo semestre', 'fecha_inicio': '2026-07-01', 'fecha_fin': '2026-12-31'}
        datos.update(kwargs)
        return datos

    def test_administrador_lista_detalle_formularios_y_menu(self):
        self.entrar('administrador')
        for url in (self.url('lista', False), self.url('detalle'),
                    self.url('crear', False), self.url('editar')):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(self.url('lista', False)), 'Nuevo período')
        self.assertContains(self.client.get(self.url('detalle')), 'href="/sgr/periodos/"')

    def test_administrador_crea_edita_cambia_estado_y_audita(self):
        self.entrar('administrador')
        respuesta = self.client.post(self.url('crear', False), self.datos())
        nuevo = Periodo.objects.get(nombre='Segundo semestre')
        self.assertRedirects(respuesta, nuevo.get_absolute_url())
        self.assertEqual(nuevo.creado_por, self.usuarios['administrador'])
        self.assertRedirects(self.client.post(reverse('sgr:periodo_editar', args=[nuevo.pk]),
                                             self.datos(nombre='Segundo editado')), nuevo.get_absolute_url())
        estado = reverse('sgr:periodo_estado', args=[nuevo.pk])
        self.assertRedirects(self.client.post(estado, {'activo': 'false'}), nuevo.get_absolute_url())
        nuevo.refresh_from_db()
        self.assertFalse(nuevo.activo)
        self.assertRedirects(self.client.post(estado, {'activo': 'true'}), nuevo.get_absolute_url())
        nuevo.refresh_from_db()
        self.assertTrue(nuevo.activo)
        self.assertEqual(set(RegistroAuditoria.objects.filter(modelo='sgr.Periodo').values_list(
            'accion', flat=True)), {'crear_periodo', 'editar_periodo', 'activar_periodo', 'desactivar_periodo'})
        self.assertEqual(Periodo.objects.count(), 2)

    def test_delegado_coordinador_solo_lectura(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            self.assertEqual(self.client.get(self.url('detalle')).status_code, 200)
            respuesta = self.client.get(self.url('lista', False))
            self.assertEqual(respuesta.status_code, 200)
            self.assertNotContains(respuesta, 'Nuevo período')
            self.assertNotContains(respuesta, 'cambiar-estado')
            for url in (self.url('crear', False), self.url('editar')):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.datos()).status_code, 403)
            self.assertEqual(self.client.post(self.url('estado'), {'activo': 'false'}).status_code, 403)
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.activo)
        self.assertEqual(Periodo.objects.count(), 1)
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_roles_operativos_sin_acceso_ni_menu(self):
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            for url in (self.url('lista', False), self.url('detalle'),
                        self.url('crear', False), self.url('editar'), self.url('estado')):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.datos()).status_code, 403)
            self.assertNotContains(self.client.get(reverse('home')), 'href="/sgr/periodos/"')

    def test_global_sin_delegacion_para_consulta_y_administracion(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            usuario = self.usuarios[rol]
            usuario.perfil.delegaciones.clear()
            Perfil.objects.filter(usuario=usuario).update(delegacion=None)
            self.entrar(rol)
            self.assertEqual(self.client.get(self.url('lista', False)).status_code, 200)
        self.entrar('administrador')
        self.assertEqual(self.client.post(self.url('crear', False), self.datos()).status_code, 302)

    def test_estado_requiere_post_y_csrf(self):
        self.entrar('administrador')
        self.assertEqual(self.client.get(self.url('estado')).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['administrador'])
        self.assertEqual(cliente.post(self.url('estado'), {'activo': 'false'}).status_code, 403)
        respuesta = cliente.get(self.url('detalle'))
        self.assertContains(respuesta, 'csrfmiddlewaretoken')
        token = cliente.cookies['csrftoken'].value
        self.assertEqual(cliente.post(self.url('estado'), {'activo': 'false',
                                                          'csrfmiddlewaretoken': token}).status_code, 302)
        self.periodo.refresh_from_db()
        self.assertFalse(self.periodo.activo)

    def test_estado_invalido_y_repetido_no_auditan(self):
        self.entrar('administrador')
        for valor in ('true', 'incorrecto'):
            self.client.post(self.url('estado'), {'activo': valor})
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.activo)
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_conflictos_en_creacion_edicion_y_reactivacion_sin_escritura(self):
        self.entrar('administrador')
        invalido = self.datos(fecha_inicio='2026-06-30')
        self.assertEqual(self.client.post(self.url('crear', False), invalido).status_code, 200)
        otro = Periodo.objects.create(nombre='Histórico', fecha_inicio='2026-07-01',
                                     fecha_fin='2026-12-31', activo=False)
        self.client.post(reverse('sgr:periodo_editar', args=[otro.pk]), self.datos(nombre='Histórico',
                         fecha_inicio='2026-01-01', fecha_fin='2026-06-30'))
        self.assertEqual(self.client.post(reverse('sgr:periodo_estado', args=[otro.pk]),
                                          {'activo': 'true'}).status_code, 302)
        otro.refresh_from_db()
        self.assertFalse(otro.activo)
        self.assertFalse(RegistroAuditoria.objects.filter(accion='activar_periodo').exists())
        respuesta = self.client.post(self.url('editar'), self.datos(nombre='   '))
        self.assertEqual(respuesta.status_code, 200)
        self.periodo.refresh_from_db()
        self.assertEqual(self.periodo.nombre, 'Primer semestre')

    def test_filtros_estado_anio_busqueda_y_orden(self):
        otro = Periodo.objects.create(nombre='Histórico extenso', fecha_inicio='2024-01-01',
                                     fecha_fin='2028-12-31', activo=False)
        self.entrar('coordinador')
        url = self.url('lista', False)
        for filtros, esperados in (
            ({'estado': 'activo'}, [self.periodo]), ({'estado': 'inactivo'}, [otro]),
            ({'anio': 2027}, [otro]), ({'anio': 2026}, [self.periodo, otro]),
            ({'buscar': 'extenso'}, [otro]),
            ({'anio': 2026, 'estado': 'activo', 'buscar': 'semestre'}, [self.periodo]),
            ({'anio': 'ayer'}, []),
        ):
            with self.subTest(filtros=filtros):
                self.assertEqual(list(self.client.get(url, filtros).context['periodos']), esperados)

    def test_auditoria_global_y_filtro_sgr_sin_fuga_territorial(self):
        self.entrar('administrador')
        self.client.post(self.url('crear', False), self.datos())
        url = reverse('auditoria:lista')
        respuesta = self.client.get(url, {'modulo': 'sgr'})
        self.assertEqual(len(respuesta.context['registros']), 1)
        self.assertContains(respuesta, 'Período creado')
        for rol in ('coordinador', 'delegado'):
            self.entrar(rol)
            respuesta = self.client.get(url)
            self.assertFalse(respuesta.context['registros'])
            self.assertNotIn(('sgr', 'SGR'), respuesta.context['form'].fields['modulo'].choices)
            self.assertFalse(self.client.get(url, {'modulo': 'sgr'}).context['registros'])
