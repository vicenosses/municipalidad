from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import RegistroAuditoria
from sgr.models import Meta, Periodo
from usuarios.models import Delegacion, Perfil, Rol


class DatosMetasMixin:
    @classmethod
    def setUpTestData(cls):
        cls.a = Delegacion.objects.create(codigo='M-A', nombre='Delegación A')
        cls.b = Delegacion.objects.create(codigo='M-B', nombre='Delegación B')
        cls.periodo = Periodo.objects.create(nombre='Período 2026', fecha_inicio='2026-01-01',
                                            fecha_fin='2026-12-31')
        cls.otro_periodo = Periodo.objects.create(nombre='Período 2027', fecha_inicio='2027-01-01',
                                                 fecha_fin='2027-12-31')
        cls.usuarios = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            usuario = get_user_model().objects.create_user(username=codigo)
            rol, _ = Rol.objects.get_or_create(codigo=codigo, defaults={'nombre': codigo})
            Perfil.objects.filter(usuario=usuario).update(rol=rol, delegacion=cls.a)
            usuario.refresh_from_db()
            usuario.perfil.delegaciones.add(cls.a)
            cls.usuarios[codigo] = usuario
        cls.meta_a = Meta.objects.create(periodo=cls.periodo, delegacion=cls.a, nombre='Áreas verdes A')
        cls.meta_b = Meta.objects.create(periodo=cls.periodo, delegacion=cls.b, nombre='Objetivo secreto B',
                                         descripcion='Texto exclusivo de B')

    def crear_meta(self, **kwargs):
        datos = dict(periodo=self.periodo, delegacion=self.a, nombre='Objetivo nuevo')
        datos.update(kwargs)
        return Meta.objects.create(**datos)

    def entrar(self, rol):
        self.client.force_login(self.usuarios[rol])

    def url(self, accion, meta=None):
        args = [(meta or self.meta_a).pk] if accion in ('detalle', 'editar', 'estado') else []
        return reverse(f'sgr:meta_{accion}', args=args)

    def datos(self, **kwargs):
        datos = dict(periodo=self.periodo.pk, delegacion=self.a.pk,
                     nombre='Objetivo nuevo', descripcion='Detalle del objetivo')
        datos.update(kwargs)
        return datos


class MetaModeloTests(DatosMetasMixin, TestCase):
    def test_valida_normaliza_y_guarda_fechas(self):
        meta = self.crear_meta(nombre='  Mejorar   áreas verdes  ')
        self.assertEqual(meta.nombre, 'Mejorar áreas verdes')
        self.assertTrue(meta.activo)
        self.assertIsNotNone(meta.creado_en)
        self.assertIsNotNone(meta.actualizado_en)

    def test_blancos_rechazados(self):
        for nombre in ('', '  \t '):
            with self.subTest(nombre=nombre), self.assertRaises(ValidationError):
                self.crear_meta(nombre=nombre)

    def test_duplicado_activo_normalizado_rechazado(self):
        with self.assertRaises(ValidationError):
            self.crear_meta(nombre='  ÁREAS VERDES A  ')

    def test_mismo_nombre_en_otro_territorio_o_periodo_permitido(self):
        self.crear_meta(nombre=self.meta_a.nombre, delegacion=self.b)
        self.crear_meta(nombre=self.meta_a.nombre, periodo=self.otro_periodo)
        self.assertEqual(Meta.objects.count(), 4)

    def test_inactiva_no_bloquea_y_reactivacion_revalida(self):
        antigua = self.crear_meta(activo=False)
        self.crear_meta()
        antigua.activo = True
        with self.assertRaises(ValidationError):
            antigua.save()
        antigua.refresh_from_db()
        self.assertFalse(antigua.activo)

    def test_edicion_excluye_propio_objeto(self):
        self.meta_a.descripcion = 'Descripción actualizada'
        self.meta_a.save()
        self.meta_a.full_clean()

    def test_periodo_inactivo_bloquea_nuevas_y_cambios_permite_validar_historico(self):
        self.periodo.activo = False
        self.periodo.save()
        self.meta_a.full_clean()
        with self.assertRaises(ValidationError):
            self.crear_meta()
        for campo, valor in (('nombre', 'Cambio'), ('descripcion', 'Cambio'), ('activo', False)):
            self.meta_a.refresh_from_db()
            setattr(self.meta_a, campo, valor)
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                self.meta_a.save()

    def test_periodo_y_delegacion_inmutables(self):
        for campo, valor in (('periodo', self.otro_periodo), ('delegacion', self.b)):
            self.meta_a.refresh_from_db()
            setattr(self.meta_a, campo, valor)
            with self.subTest(campo=campo), self.assertRaises(ValidationError):
                self.meta_a.save()

    def test_creador_set_null_y_padres_protegidos(self):
        usuario = get_user_model().objects.create_user(username='creador_meta')
        meta = self.crear_meta(creado_por=usuario)
        usuario.delete()
        meta.refresh_from_db()
        self.assertIsNone(meta.creado_por)
        with self.assertRaises(ProtectedError):
            self.periodo.delete()


class MetaPermisosTests(DatosMetasMixin, TestCase):
    def test_admin_ve_todas_y_crea_para_cualquier_delegacion(self):
        self.entrar('administrador')
        respuesta = self.client.get(self.url('lista'))
        self.assertContains(respuesta, self.meta_a.nombre)
        self.assertContains(respuesta, self.meta_b.nombre)
        self.assertEqual(self.client.get(self.url('detalle', self.meta_b)).status_code, 200)
        respuesta = self.client.post(self.url('crear'), self.datos(delegacion=self.b.pk))
        nueva = Meta.objects.get(nombre='Objetivo nuevo')
        self.assertRedirects(respuesta, nueva.get_absolute_url())
        self.assertEqual(nueva.delegacion, self.b)
        self.assertEqual(nueva.creado_por, self.usuarios['administrador'])

    def test_delegado_y_coordinador_crean_en_alcance_ignoran_post_delegacion(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.url('crear'))
            self.assertNotIn('delegacion', respuesta.context['form'].fields)
            nombre = f'Creada por {rol}'
            respuesta = self.client.post(self.url('crear'), self.datos(
                nombre=nombre, delegacion=self.b.pk, activo='false'))
            nueva = Meta.objects.get(nombre=nombre)
            self.assertRedirects(respuesta, nueva.get_absolute_url())
            self.assertEqual(nueva.delegacion, self.a)
            self.assertTrue(nueva.activo)

    def test_edicion_solo_nombre_descripcion_y_auditoria(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.url('editar'))
            self.assertEqual(set(respuesta.context['form'].fields), {'nombre', 'descripcion'})
            respuesta = self.client.post(self.url('editar'), self.datos(
                nombre=f'Editada {rol}', periodo=self.otro_periodo.pk,
                delegacion=self.b.pk, activo='false', creado_por=self.usuarios['verificador'].pk))
            self.assertRedirects(respuesta, self.meta_a.get_absolute_url())
            self.meta_a.refresh_from_db()
            self.assertEqual(self.meta_a.nombre, f'Editada {rol}')
            self.assertEqual(self.meta_a.periodo, self.periodo)
            self.assertEqual(self.meta_a.delegacion, self.a)
            self.assertTrue(self.meta_a.activo)
            self.assertIsNone(self.meta_a.creado_por)
        self.assertEqual(RegistroAuditoria.objects.filter(accion='editar_meta').count(), 3)

    def test_delegado_y_coordinador_no_acceden_otro_territorio(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            self.assertNotContains(self.client.get(self.url('lista')), self.meta_b.nombre)
            for accion in ('detalle', 'editar'):
                self.assertEqual(self.client.get(self.url(accion, self.meta_b)).status_code, 404)
            self.assertEqual(self.client.post(self.url('editar', self.meta_b), self.datos()).status_code, 404)
            self.assertIn(self.client.post(self.url('estado', self.meta_b),
                                           {'activo': 'false'}).status_code, (403, 404))
        self.meta_b.refresh_from_db()
        self.assertTrue(self.meta_b.activo)
        self.assertEqual(self.meta_b.nombre, 'Objetivo secreto B')
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_admin_y_delegado_cambian_estado_coordinador_denegado(self):
        for rol, meta in (('administrador', self.meta_b), ('delegado', self.meta_a)):
            self.entrar(rol)
            for activo in ('false', 'true'):
                self.assertRedirects(self.client.post(self.url('estado', meta), {'activo': activo}),
                                     meta.get_absolute_url())
                meta.refresh_from_db()
                self.assertEqual(meta.activo, activo == 'true')
        self.assertEqual(RegistroAuditoria.objects.filter(accion='activar_meta').count(), 2)
        self.assertEqual(RegistroAuditoria.objects.filter(accion='desactivar_meta').count(), 2)
        self.entrar('coordinador')
        self.assertEqual(self.client.post(self.url('estado'), {'activo': 'false'}).status_code, 403)
        self.assertNotContains(self.client.get(self.url('detalle')), 'cambiar-estado')

    def test_sin_delegacion_valida_deny_by_default(self):
        for rol in ('delegado', 'coordinador'):
            usuario = self.usuarios[rol]
            usuario.perfil.delegaciones.clear()
            self.entrar(rol)
            session = self.client.session
            session['delegacion_activa_id'] = self.b.pk
            session.save()
            self.assertFalse(self.client.get(self.url('lista')).context['metas'])
            self.assertEqual(self.client.get(self.url('crear')).status_code, 403)
            self.assertEqual(self.client.post(self.url('crear'), self.datos()).status_code, 403)
            self.assertEqual(self.client.post(self.url('editar'), self.datos()).status_code, 404)
            self.assertFalse(self.client.get(self.periodo.get_absolute_url()).context['metas'])

    def test_delegacion_inactiva_no_recibe_metas(self):
        self.a.activa = False
        self.a.save()
        self.entrar('delegado')
        self.assertFalse(self.client.get(self.url('lista')).context['metas'])
        self.assertEqual(self.client.post(self.url('crear'), self.datos()).status_code, 403)

    def test_cambio_de_delegacion_autorizada(self):
        usuario = self.usuarios['coordinador']
        usuario.perfil.delegaciones.add(self.b)
        self.entrar('coordinador')
        session = self.client.session
        session['delegacion_activa_id'] = self.b.pk
        session.save()
        respuesta = self.client.get(self.url('lista'))
        self.assertContains(respuesta, self.meta_b.nombre)
        self.assertNotContains(respuesta, self.meta_a.nombre)
        self.assertEqual(self.client.post(self.url('editar'), self.datos()).status_code, 404)

    def test_funcionario_verificador_denegados_en_rutas_directas(self):
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            for accion in ('lista', 'crear', 'detalle', 'editar', 'estado'):
                url = self.url(accion)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.datos()).status_code, 403)
            desde = reverse('sgr:meta_desde_periodo', args=[self.periodo.pk])
            self.assertEqual(self.client.post(desde, self.datos()).status_code, 403)

    def test_estado_requiere_post_y_csrf(self):
        self.entrar('delegado')
        self.assertEqual(self.client.get(self.url('estado')).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['delegado'])
        self.assertEqual(cliente.post(self.url('estado'), {'activo': 'false'}).status_code, 403)
        respuesta = cliente.get(self.url('detalle'))
        self.assertContains(respuesta, 'csrfmiddlewaretoken')
        token = cliente.cookies['csrftoken'].value
        self.assertEqual(cliente.post(self.url('estado'), {'activo': 'false',
                                                          'csrfmiddlewaretoken': token}).status_code, 302)
        self.meta_a.refresh_from_db()
        self.assertFalse(self.meta_a.activo)

    def test_periodo_inactivo_conserva_consulta_bloquea_operaciones_todos_roles(self):
        self.periodo.activo = False
        self.periodo.save()
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            self.assertContains(self.client.get(self.url('detalle')), self.meta_a.nombre)
            self.assertContains(self.client.get(self.url('lista')), self.meta_a.nombre)
            self.assertEqual(self.client.get(self.url('editar')).status_code, 403)
            self.assertEqual(self.client.post(self.url('editar'), self.datos()).status_code, 403)
            self.assertEqual(self.client.post(self.url('estado'), {'activo': 'false'}).status_code, 403)
            self.assertEqual(self.client.post(self.url('crear'), self.datos()).status_code, 200)
            form = self.client.get(self.url('crear')).context['form']
            self.assertNotIn(self.periodo, form.fields['periodo'].queryset)
            respuesta = self.client.get(self.periodo.get_absolute_url())
            self.assertNotContains(respuesta, 'Nueva Meta')
            self.assertNotContains(respuesta, f'/sgr/metas/{self.meta_a.pk}/editar/')
            self.assertNotContains(respuesta, f'/sgr/metas/{self.meta_a.pk}/cambiar-estado/')
        self.assertEqual(Meta.objects.count(), 2)
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_reactivar_duplicada_y_estado_invalido_no_escriben_eventos(self):
        antigua = self.crear_meta(activo=False)
        self.crear_meta()
        self.entrar('delegado')
        self.client.post(self.url('estado', antigua), {'activo': 'true'})
        antigua.refresh_from_db()
        self.assertFalse(antigua.activo)
        for valor in ('incorrecto', 'true'):
            self.client.post(self.url('estado'), {'activo': valor})
        self.assertFalse(RegistroAuditoria.objects.exists())


class MetaIntegracionTests(DatosMetasMixin, TestCase):
    def test_filtros_admin_y_combinaciones(self):
        historica = self.crear_meta(periodo=self.otro_periodo, activo=False, descripcion='Texto único')
        self.entrar('administrador')
        for filtros, ids in (
            ({'periodo': self.otro_periodo.pk}, {historica.pk}),
            ({'estado': 'inactiva'}, {historica.pk}),
            ({'delegacion': self.b.pk}, {self.meta_b.pk}),
            ({'buscar': 'único'}, {historica.pk}),
            ({'buscar': 'Objetivo secreto'}, {self.meta_b.pk}),
            ({'periodo': self.periodo.pk, 'estado': 'activa', 'delegacion': self.a.pk}, {self.meta_a.pk}),
            ({'estado': 'incorrecto'}, set()),
        ):
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(self.url('lista'), filtros)
                self.assertEqual({m.pk for m in respuesta.context['metas']}, ids)

    def test_filtros_territoriales_no_amplian_alcance(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.url('lista'), {'delegacion': self.b.pk})
            self.assertEqual(list(respuesta.context['metas']), [self.meta_a])
            self.assertNotIn('delegacion', respuesta.context['form'].fields)
            respuesta = self.client.get(self.url('lista'), {'delegacion': self.b.pk,
                                       'periodo': self.periodo.pk, 'buscar': 'exclusivo de B'})
            self.assertFalse(respuesta.context['metas'])

    def test_periodo_muestra_solo_metas_autorizadas(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.periodo.get_absolute_url())
            self.assertContains(respuesta, self.meta_a.nombre)
            if rol == 'administrador':
                self.assertContains(respuesta, self.meta_b.nombre)
            else:
                self.assertNotContains(respuesta, self.meta_b.nombre)
            self.assertContains(respuesta, 'Nueva Meta')

    def test_crear_desde_periodo_fija_origen_ante_post_manipulado(self):
        url = reverse('sgr:meta_desde_periodo', args=[self.periodo.pk])
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(url)
            self.assertTrue(respuesta.context['form'].fields['periodo'].disabled)
            self.assertEqual(respuesta.context['form'].fields['periodo'].initial, self.periodo.pk)
            nombre = f'Desde período {rol}'
            respuesta = self.client.post(url, self.datos(nombre=nombre, periodo=self.otro_periodo.pk))
            meta = Meta.objects.get(nombre=nombre)
            self.assertRedirects(respuesta, meta.get_absolute_url())
            self.assertEqual(meta.periodo, self.periodo)

    def test_origen_inactivo_o_inexistente_rechazado(self):
        self.periodo.activo = False
        self.periodo.save()
        self.entrar('administrador')
        for pk, codigo in ((self.periodo.pk, 403), (99999, 404)):
            url = reverse('sgr:meta_desde_periodo', args=[pk])
            self.assertEqual(self.client.get(url).status_code, codigo)
            self.assertEqual(self.client.post(url, self.datos()).status_code, codigo)

    def test_auditoria_meta_territorial_periodo_global_y_filtro_sgr(self):
        self.entrar('administrador')
        self.client.post(reverse('sgr:periodo_editar', args=[self.periodo.pk]), {
            'nombre': self.periodo.nombre, 'fecha_inicio': '2026-01-01', 'fecha_fin': '2026-12-31'})
        self.client.post(self.url('crear'), self.datos(nombre='Meta nueva A'))
        self.client.post(self.url('crear'), self.datos(nombre='Meta nueva B', delegacion=self.b.pk))
        url = reverse('auditoria:lista')
        respuesta = self.client.get(url, {'modulo': 'sgr'})
        self.assertEqual(len(respuesta.context['registros']), 3)
        self.assertContains(respuesta, 'Meta nueva B')
        self.assertContains(respuesta, 'Meta creada')
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(url, {'modulo': 'sgr'})
            self.assertEqual(len(respuesta.context['registros']), 1)
            self.assertContains(respuesta, 'Meta nueva A')
            self.assertNotContains(respuesta, 'Meta nueva B')
            self.assertTrue(all(r.modelo == 'sgr.Meta' for r in respuesta.context['registros']))

    def test_paginacion_conserva_filtros(self):
        for numero in range(51):
            self.crear_meta(nombre=f'Paginada {numero:02d}')
        self.entrar('coordinador')
        respuesta = self.client.get(self.url('lista'), {'periodo': self.periodo.pk,
                                    'estado': 'activa', 'buscar': 'Paginada', 'page': 2})
        self.assertEqual(len(respuesta.context['metas']), 1)
        self.assertNotIn('page=', respuesta.context['query_params'])
        self.assertContains(respuesta, 'estado=activa&amp;buscar=Paginada')
