from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import RequestFactory, TestCase
from django.urls import reverse

from atenciones.forms import AtencionCiudadanaForm
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from catalogos.models import (
    SolicitudCatalogoGeneral,
    SubAtencion,
    TipoAtencion,
)
from usuarios.models import Delegacion, Perfil, Rol


User = get_user_model()


class CatalogoScopeModelTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='CAT-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='CAT-B', nombre='Delegación B')

    def test_migracion_conserva_registros_existentes_como_generales(self):
        migration = MigrationLoader(connection).get_migration(
            'catalogos',
            '0002_subatencion_delegacion_subatencion_es_general_and_more',
        )
        campos = {
            (operation.model_name, operation.name): operation.field
            for operation in migration.operations
            if operation.__class__.__name__ == 'AddField'
        }

        self.assertTrue(campos[('tipoatencion', 'es_general')].default)
        self.assertTrue(campos[('subatencion', 'es_general')].default)
        self.assertTrue(campos[('tipoatencion', 'delegacion')].null)
        self.assertTrue(campos[('subatencion', 'delegacion')].null)

    def test_categoria_general_es_valida_sin_delegacion(self):
        tipo = TipoAtencion.objects.create(codigo='GENERAL', nombre='General')

        self.assertTrue(tipo.es_general)
        self.assertIsNone(tipo.delegacion_id)

    def test_categoria_delegacion_requiere_delegacion_y_general_no_la_admite(self):
        territorial_sin_delegacion = TipoAtencion(
            codigo='SIN-DEL',
            nombre='Sin delegación',
            es_general=False,
        )
        general_con_delegacion = TipoAtencion(
            codigo='GEN-DEL',
            nombre='General con delegación',
            es_general=True,
            delegacion=self.delegacion_a,
        )

        for tipo in (territorial_sin_delegacion, general_con_delegacion):
            with self.subTest(tipo=tipo.codigo):
                with self.assertRaises(ValidationError):
                    tipo.save()

    def test_categoria_delegacion_requiere_una_delegacion_valida(self):
        tipo = TipoAtencion.objects.create(
            codigo='LOCAL-A',
            nombre='Local A',
            es_general=False,
            delegacion=self.delegacion_a,
        )

        self.assertFalse(tipo.es_general)
        self.assertEqual(tipo.delegacion, self.delegacion_a)

    def test_subcategoria_territorial_debe_corresponder_a_categoria(self):
        tipo = TipoAtencion.objects.create(
            codigo='TIPO-A',
            nombre='Categoría A',
            es_general=False,
            delegacion=self.delegacion_a,
        )
        incompatibles = (
            SubAtencion(
                codigo='SUB-GEN',
                nombre='General incompatible',
                tipo=tipo,
            ),
            SubAtencion(
                codigo='SUB-B',
                nombre='Delegación B',
                tipo=tipo,
                es_general=False,
                delegacion=self.delegacion_b,
            ),
        )

        for subatencion in incompatibles:
            with self.subTest(codigo=subatencion.codigo):
                with self.assertRaises(ValidationError):
                    subatencion.save()

        permitida = SubAtencion.objects.create(
            codigo='SUB-A',
            nombre='Delegación A',
            tipo=tipo,
            es_general=False,
            delegacion=self.delegacion_a,
        )
        self.assertEqual(permitida.delegacion, self.delegacion_a)

    def test_categoria_general_admite_subcategoria_general_y_territorial(self):
        tipo = TipoAtencion.objects.create(codigo='TIP-GEN', nombre='Categoría general')
        general = SubAtencion.objects.create(
            codigo='SUB-GEN',
            nombre='General',
            tipo=tipo,
        )
        territorial = SubAtencion.objects.create(
            codigo='SUB-A',
            nombre='Territorial',
            tipo=tipo,
            es_general=False,
            delegacion=self.delegacion_a,
        )

        self.assertTrue(general.es_general)
        self.assertIsNone(general.delegacion_id)
        self.assertEqual(territorial.delegacion, self.delegacion_a)

    def test_codigo_subcategoria_es_automatico_unico_e_inmutable(self):
        tipo = TipoAtencion.objects.create(codigo='AUTO-TIPO', nombre='Categoría')
        primera = SubAtencion.objects.create(
            codigo='HACK',
            nombre='Primera',
            tipo=tipo,
        )
        segunda = SubAtencion.objects.create(
            codigo='MANUAL',
            nombre='Segunda',
            tipo=tipo,
        )
        codigo_original = primera.codigo

        primera.codigo = 'OTRO-HACK'
        primera.nombre = 'Nombre editado'
        primera.save()

        self.assertRegex(codigo_original, r'^SUB-\d{3,}$')
        self.assertNotEqual(primera.codigo, 'OTRO-HACK')
        self.assertNotEqual(primera.codigo, segunda.codigo)

    def test_colision_codigo_subcategoria_se_resuelve_sin_sobrescribir(self):
        tipo = TipoAtencion.objects.create(codigo='COL-TIPO', nombre='Categoría')
        SubAtencion.objects.bulk_create([
            SubAtencion(
                pk=1,
                codigo='SUB-002',
                nombre='Histórica',
                tipo=tipo,
            ),
        ])

        nueva = SubAtencion.objects.create(
            codigo='HACK',
            nombre='Nueva',
            tipo=tipo,
        )

        self.assertEqual(nueva.codigo, 'SUB-003')
        self.assertEqual(SubAtencion.objects.filter(codigo='SUB-002').count(), 1)

    def test_categoria_no_puede_volverse_territorial_con_subcategorias_generales(self):
        tipo = TipoAtencion.objects.create(codigo='TIP-GEN', nombre='Categoría general')
        SubAtencion.objects.create(
            codigo='SUB-GEN',
            nombre='General',
            tipo=tipo,
        )
        tipo.es_general = False
        tipo.delegacion = self.delegacion_a

        with self.assertRaises(ValidationError):
            tipo.save()


class CatalogoScopePermissionTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='PERM-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='PERM-B', nombre='Delegación B')
        self.roles = {}
        self.users = {}
        for codigo in ('administrador', 'coordinador', 'delegado', 'funcionario', 'verificador'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol
            user = User.objects.create_user(username=codigo, password='clave-segura')
            perfil = Perfil.objects.get(usuario=user)
            perfil.rol = rol
            perfil.delegacion = self.delegacion_a
            perfil.save()
            perfil.delegaciones.set([self.delegacion_a])
            self.users[codigo] = user

    def iniciar_sesion(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = (
            'global' if user == self.users['administrador'] else self.delegacion_a.pk)
        session.save()

    def test_pagina_principal_disponible_solo_a_roles_de_catalogos(self):
        for rol in ('administrador', 'coordinador', 'delegado'):
            with self.subTest(rol=rol):
                self.iniciar_sesion(self.users[rol])
                respuesta = self.client.get(reverse('catalogos:inicio'))
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'Tipos de Atención')
                self.assertContains(respuesta, 'Administrar Tipos de Atención')
                self.assertContains(respuesta, 'Administrar subcategorías')
                self.assertContains(respuesta, 'Solicitudes generales')

        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.iniciar_sesion(self.users[rol])
                respuesta = self.client.get(reverse('catalogos:inicio'))
                self.assertEqual(respuesta.status_code, 403)

    def test_menu_principal_unifica_acceso_a_catalogos(self):
        self.iniciar_sesion(self.users['coordinador'])

        respuesta = self.client.get(reverse('home'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta,
            f'href="{reverse("catalogos:inicio")}"',
        )
        self.assertNotContains(respuesta, '>Subatenciones</a>')

        self.iniciar_sesion(self.users['funcionario'])
        sin_permisos = self.client.get(reverse('home'))
        self.assertNotContains(sin_permisos, '>Tipos de Atención</a>')

    def test_navegacion_interna_apunta_a_secciones_y_marca_la_actual(self):
        self.iniciar_sesion(self.users['coordinador'])

        tipos = self.client.get(reverse('catalogos:tipo_lista'))
        self.assertEqual(tipos.status_code, 200)
        self.assertContains(tipos, '<h2 class="h4 fw-bold mb-0">Tipos de Atención</h2>', html=True)
        self.assertNotContains(tipos, '<h2 class="h4 fw-bold mb-0">Categorías</h2>', html=True)
        self.assertContains(
            tipos,
            f'<a class="btn btn-custom-red" href="{reverse("catalogos:tipo_lista")}" aria-current="page">Tipos de Atención</a>',
            html=True,
        )
        self.assertNotContains(tipos, '>Categorías</a>')
        self.assertContains(
            tipos,
            f'<a class="btn btn-custom-red" href="{reverse("catalogos:sub_lista")}">Subcategorías</a>',
            html=True,
        )
        self.assertContains(
            tipos,
            f'<a class="btn btn-custom-red" href="{reverse("catalogos:solicitud_lista")}">Solicitudes generales</a>',
            html=True,
        )

        subcategorias = self.client.get(reverse('catalogos:sub_lista'))
        self.assertContains(
            subcategorias,
            f'<a class="btn btn-custom-red" href="{reverse("catalogos:sub_lista")}" aria-current="page">Subcategorías</a>',
            html=True,
        )

        solicitudes = self.client.get(reverse('catalogos:solicitud_lista'))
        self.assertContains(
            solicitudes,
            f'<a class="btn btn-custom-red" href="{reverse("catalogos:solicitud_lista")}" aria-current="page">Solicitudes generales</a>',
            html=True,
        )

    def test_navegacion_no_muestra_solicitudes_a_funcionario_ni_verificador(self):
        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.iniciar_sesion(self.users[rol])
                respuesta = self.client.get(reverse('catalogos:tipo_lista'))
                self.assertEqual(respuesta.status_code, 403)

    def crear_categoria(self, codigo, *, general=True, delegacion=None):
        return TipoAtencion.objects.create(
            codigo=codigo,
            nombre=codigo,
            es_general=general,
            delegacion=delegacion,
        )

    def crear_subcategoria(self, codigo, tipo, *, general=True, delegacion=None):
        return SubAtencion.objects.create(
            codigo=codigo,
            nombre=codigo,
            tipo=tipo,
            es_general=general,
            delegacion=delegacion,
        )

    def test_listados_ordenan_activos_recientes_y_desactivados_al_final(self):
        self.iniciar_sesion(self.users['administrador'])
        antiguo = self.crear_categoria('ORD-ANT')
        reciente = self.crear_categoria('ORD-REC')
        inactivo = self.crear_categoria('ORD-INACT')
        inactivo.activo = False
        inactivo.save()
        respuesta = self.client.get(reverse('catalogos:tipo_lista'))
        self.assertEqual(list(respuesta.context['tipos']), [reciente, antiguo, inactivo])
        sub_antigua = self.crear_subcategoria('SUB-ANT', antiguo)
        sub_reciente = self.crear_subcategoria('SUB-REC', antiguo)
        sub_inactiva = self.crear_subcategoria('SUB-INACT', antiguo)
        sub_inactiva.activo = False
        sub_inactiva.save()
        respuesta = self.client.get(reverse('catalogos:sub_lista'))
        self.assertEqual(list(respuesta.context['subs']), [sub_reciente, sub_antigua, sub_inactiva])

    def test_botones_de_estado_activan_y_desactivan_tipo(self):
        self.iniciar_sesion(self.users['administrador'])
        tipo = self.crear_categoria('ESTADO-TEST')
        url = reverse('catalogos:tipo_desactivar', args=[tipo.pk])
        self.assertContains(self.client.get(reverse('catalogos:tipo_lista')), 'Desactivar')
        self.client.post(url, {'activo': 'false'})
        tipo.refresh_from_db()
        self.assertFalse(tipo.activo)
        self.assertContains(self.client.get(reverse('catalogos:tipo_lista')), 'Activar')
        self.client.post(url, {'activo': 'true'})
        tipo.refresh_from_db()
        self.assertTrue(tipo.activo)

    def test_opcion_todas_las_delegaciones_crea_catalogos_generales(self):
        self.iniciar_sesion(self.users['administrador'])
        respuesta = self.client.get(reverse('catalogos:tipo_crear'))
        self.assertContains(respuesta, 'Todas las delegaciones (global)')
        respuesta = self.client.post(reverse('catalogos:tipo_crear'), {
            'codigo': 'GLOBAL-OPCION', 'nombre': 'Tipo global', 'delegacion': '', 'activo': 'on',
        })
        self.assertEqual(respuesta.status_code, 302)
        tipo = TipoAtencion.objects.get(codigo='GLOBAL-OPCION')
        self.assertTrue(tipo.es_general)
        self.assertIsNone(tipo.delegacion_id)
        respuesta = self.client.post(reverse('catalogos:sub_crear'), {
            'nombre': 'Sub global', 'tipo': tipo.pk, 'delegacion': '',
        })
        self.assertEqual(respuesta.status_code, 302)
        sub = SubAtencion.objects.get(nombre='Sub global')
        self.assertTrue(sub.es_general)
        self.assertIsNone(sub.delegacion_id)

    def test_administrador_crea_categoria_general_y_de_cualquier_delegacion(self):
        self.iniciar_sesion(self.users['administrador'])

        general_response = self.client.post(
            reverse('catalogos:tipo_crear'),
            {'codigo': 'ADMIN-G', 'nombre': 'General admin', 'es_general': 'on'},
        )
        territorial_response = self.client.post(
            reverse('catalogos:tipo_crear'),
            {
                'codigo': 'ADMIN-B',
                'nombre': 'Territorial B',
                'delegacion': self.delegacion_b.pk,
            },
        )

        self.assertEqual(general_response.status_code, 302)
        self.assertEqual(territorial_response.status_code, 302)
        self.assertTrue(TipoAtencion.objects.get(codigo='ADMIN-G').es_general)
        self.assertEqual(
            TipoAtencion.objects.get(codigo='ADMIN-B').delegacion,
            self.delegacion_b,
        )

    def test_coordinador_crea_somente_en_su_delegacion_y_no_puede_manipular_alcance(self):
        self.iniciar_sesion(self.users['coordinador'])

        response = self.client.post(
            reverse('catalogos:tipo_crear'),
            {'codigo': 'COORD-A', 'nombre': 'Coordinación local'},
        )
        general_manipulado = self.client.post(
            reverse('catalogos:tipo_crear'),
            {
                'codigo': 'COORD-G',
                'nombre': 'General manipulado',
                'es_general': 'on',
            },
        )
        delegacion_manipulada = self.client.post(
            reverse('catalogos:tipo_crear'),
            {
                'codigo': 'COORD-B',
                'nombre': 'Delegación manipulada',
                'delegacion': self.delegacion_b.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        local = TipoAtencion.objects.get(codigo='COORD-A')
        self.assertFalse(local.es_general)
        self.assertEqual(local.delegacion, self.delegacion_a)
        self.assertEqual(general_manipulado.status_code, 200)
        self.assertEqual(delegacion_manipulada.status_code, 200)
        self.assertFalse(TipoAtencion.objects.filter(codigo__in=['COORD-G', 'COORD-B']).exists())

    def test_delegado_crea_somente_en_su_delegacion(self):
        self.iniciar_sesion(self.users['delegado'])

        local = self.client.post(
            reverse('catalogos:tipo_crear'),
            {'codigo': 'DEL-A', 'nombre': 'Delegación local'},
        )
        general = self.client.post(
            reverse('catalogos:tipo_crear'),
            {'codigo': 'DEL-G', 'nombre': 'General manipulado', 'es_general': 'on'},
        )
        otra = self.client.post(
            reverse('catalogos:tipo_crear'),
            {
                'codigo': 'DEL-B',
                'nombre': 'Delegación ajena',
                'delegacion': self.delegacion_b.pk,
            },
        )

        self.assertEqual(local.status_code, 302)
        self.assertEqual(TipoAtencion.objects.get(codigo='DEL-A').delegacion, self.delegacion_a)
        self.assertEqual(general.status_code, 200)
        self.assertEqual(otra.status_code, 200)
        self.assertFalse(TipoAtencion.objects.filter(codigo__in=['DEL-G', 'DEL-B']).exists())

    def test_funcionario_y_verificador_no_pueden_administrar_categorias(self):
        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.iniciar_sesion(self.users[rol])
                respuesta = self.client.get(reverse('catalogos:tipo_crear'))
                self.assertEqual(respuesta.status_code, 403)

    def test_django_admin_no_permite_eliminar_catalogos_fisicamente(self):
        request = RequestFactory().get('/admin/')

        self.assertFalse(admin.site._registry[TipoAtencion].has_delete_permission(request))
        self.assertFalse(admin.site._registry[SubAtencion].has_delete_permission(request))
        self.assertIn(
            'codigo',
            admin.site._registry[SubAtencion].get_readonly_fields(request),
        )

    def test_categoria_general_usable_como_padre_de_subcategoria_territorial(self):
        tipo = self.crear_categoria('PADRE-GENERAL')
        self.iniciar_sesion(self.users['coordinador'])

        respuesta = self.client.post(
            reverse('catalogos:sub_crear'),
            {'codigo': 'SUB-COORD', 'nombre': 'Sub local', 'tipo': tipo.pk},
        )

        self.assertEqual(respuesta.status_code, 302)
        sub = SubAtencion.objects.get(nombre='Sub local')
        self.assertRegex(sub.codigo, r'^SUB-\d{3,}$')
        self.assertFalse(sub.es_general)
        self.assertEqual(sub.delegacion, self.delegacion_a)
        self.assertEqual(sub.tipo, tipo)

    def test_administrador_crea_subcategoria_general_y_de_cualquier_delegacion(self):
        tipo = self.crear_categoria('ADMIN-SUB-TIPO')
        self.iniciar_sesion(self.users['administrador'])

        general = self.client.post(
            reverse('catalogos:sub_crear'),
            {
                'codigo': 'ADMIN-SUB-G',
                'nombre': 'Sub general',
                'tipo': tipo.pk,
                'es_general': 'on',
            },
        )
        territorial = self.client.post(
            reverse('catalogos:sub_crear'),
            {
                'codigo': 'ADMIN-SUB-B',
                'nombre': 'Sub B',
                'tipo': tipo.pk,
                'delegacion': self.delegacion_b.pk,
            },
        )

        self.assertEqual(general.status_code, 302)
        self.assertEqual(territorial.status_code, 302)
        sub_general = SubAtencion.objects.get(nombre='Sub general')
        self.assertTrue(sub_general.es_general)
        self.assertRegex(sub_general.codigo, r'^SUB-\d{3,}$')
        self.assertEqual(
            SubAtencion.objects.get(nombre='Sub B').delegacion,
            self.delegacion_b,
        )

    def test_subcategoria_respeta_alcance_y_categoria_padre(self):
        general = self.crear_categoria('SUB-PADRE-G')
        local_a = self.crear_categoria(
            'SUB-PADRE-A',
            general=False,
            delegacion=self.delegacion_a,
        )
        local_b = self.crear_categoria(
            'SUB-PADRE-B',
            general=False,
            delegacion=self.delegacion_b,
        )
        self.iniciar_sesion(self.users['coordinador'])

        permitida = self.client.post(
            reverse('catalogos:sub_crear'),
            {'codigo': 'SUB-OK', 'nombre': 'Permitida', 'tipo': general.pk},
        )
        bajo_categoria_local = self.client.post(
            reverse('catalogos:sub_crear'),
            {'codigo': 'SUB-LOCAL', 'nombre': 'Local', 'tipo': local_a.pk},
        )
        ajena = self.client.post(
            reverse('catalogos:sub_crear'),
            {'codigo': 'SUB-AJENA', 'nombre': 'Ajena', 'tipo': local_b.pk},
        )
        general_manipulada = self.client.post(
            reverse('catalogos:sub_crear'),
            {
                'codigo': 'SUB-G-MANIP',
                'nombre': 'General manipulada',
                'tipo': general.pk,
                'es_general': 'on',
            },
        )

        self.assertEqual(permitida.status_code, 302)
        self.assertEqual(bajo_categoria_local.status_code, 302)
        for nombre in ('Permitida', 'Local'):
            sub = SubAtencion.objects.get(nombre=nombre)
            self.assertFalse(sub.es_general)
            self.assertEqual(sub.delegacion, self.delegacion_a)
        self.assertEqual(ajena.status_code, 200)
        self.assertEqual(general_manipulada.status_code, 200)
        self.assertFalse(SubAtencion.objects.filter(
            nombre__in=['Ajena', 'General manipulada']
        ).exists())

    def test_catalogos_generales_son_visibles_pero_solo_admin_puede_editarlos(self):
        general = self.crear_categoria('VIS-GENERAL')
        local_a = self.crear_categoria(
            'VIS-A',
            general=False,
            delegacion=self.delegacion_a,
        )
        local_b = self.crear_categoria(
            'VIS-B',
            general=False,
            delegacion=self.delegacion_b,
        )
        self.iniciar_sesion(self.users['delegado'])

        listado = self.client.get(reverse('catalogos:tipo_lista'))
        self.assertContains(listado, general.codigo)
        self.assertContains(listado, local_a.codigo)
        self.assertNotContains(listado, local_b.codigo)
        self.assertEqual(
            self.client.get(reverse('catalogos:tipo_editar', args=[general.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('catalogos:tipo_editar', args=[local_b.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('catalogos:tipo_editar', args=[local_a.pk])).status_code,
            200,
        )

    def test_coordinador_no_puede_cambiar_alcance_en_edicion_por_post(self):
        tipo = self.crear_categoria(
            'EDIT-A',
            general=False,
            delegacion=self.delegacion_a,
        )
        sub = self.crear_subcategoria(
            'EDIT-SUB-A',
            tipo,
            general=False,
            delegacion=self.delegacion_a,
        )
        self.iniciar_sesion(self.users['coordinador'])

        tipo_response = self.client.post(
            reverse('catalogos:tipo_editar', args=[tipo.pk]),
            {
                'codigo': tipo.codigo,
                'nombre': 'Cambio de alcance',
                'descripcion': '',
                'activo': 'on',
                'es_general': 'on',
                'delegacion': self.delegacion_b.pk,
            },
        )
        sub_response = self.client.post(
            reverse('catalogos:sub_editar', args=[sub.pk]),
            {
                'codigo': sub.codigo,
                'nombre': 'Cambio de alcance',
                'tipo': tipo.pk,
                'activo': 'on',
                'es_general': 'on',
                'delegacion': self.delegacion_b.pk,
            },
        )

        tipo.refresh_from_db()
        sub.refresh_from_db()
        self.assertEqual(tipo_response.status_code, 200)
        self.assertEqual(sub_response.status_code, 200)
        self.assertFalse(tipo.es_general)
        self.assertEqual(tipo.delegacion, self.delegacion_a)
        self.assertFalse(sub.es_general)
        self.assertEqual(sub.delegacion, self.delegacion_a)


class AtencionCatalogoScopeTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='FORM-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='FORM-B', nombre='Delegación B')
        rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.user = User.objects.create_user(username='form-user', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.user)
        perfil.rol = rol
        perfil.delegacion = self.delegacion_a
        perfil.save()
        perfil.delegaciones.set([self.delegacion_a])
        self.tipo_general = TipoAtencion.objects.create(
            codigo='FORM-G',
            nombre='General',
        )
        self.tipo_a = TipoAtencion.objects.create(
            codigo='FORM-A-LOCAL',
            nombre='Local A',
            es_general=False,
            delegacion=self.delegacion_a,
        )
        self.tipo_b = TipoAtencion.objects.create(
            codigo='FORM-B-LOCAL',
            nombre='Local B',
            es_general=False,
            delegacion=self.delegacion_b,
        )
        self.sub_general = SubAtencion.objects.create(
            codigo='FORM-SG',
            nombre='Sub general',
            tipo=self.tipo_general,
        )
        self.sub_a = SubAtencion.objects.create(
            codigo='FORM-SA',
            nombre='Sub A',
            tipo=self.tipo_general,
            es_general=False,
            delegacion=self.delegacion_a,
        )
        self.sub_b = SubAtencion.objects.create(
            codigo='FORM-SB',
            nombre='Sub B',
            tipo=self.tipo_general,
            es_general=False,
            delegacion=self.delegacion_b,
        )
        self.sub_a_local = SubAtencion.objects.create(
            codigo='FORM-SAL',
            nombre='Sub local A',
            tipo=self.tipo_a,
            es_general=False,
            delegacion=self.delegacion_a,
        )
        self.sub_inactive = SubAtencion.objects.create(
            codigo='FORM-SI',
            nombre='Sub inactiva',
            tipo=self.tipo_general,
        )
        self.tipo_inactive = TipoAtencion.objects.create(
            codigo='FORM-TI',
            nombre='Categoría inactiva',
            activo=False,
        )
        self.tipo_inactive_sub = SubAtencion.objects.create(
            codigo='FORM-SIT',
            nombre='Sub de categoría inactiva',
            tipo=self.tipo_inactive,
            es_general=False,
            delegacion=self.delegacion_a,
        )
        self.sub_inactive.activo = False
        self.sub_inactive.save(update_fields=['activo'])

    def formulario(self, data=None):
        request = RequestFactory().post('/')
        request.user = self.user
        request.session = {'delegacion_activa_id': self.delegacion_a.pk}
        return AtencionCiudadanaForm(data=data, request=request)

    def datos(self, tipo, sub):
        return {
            'titulo': 'Actividad de prueba',
            'fecha': '2026-10-25',
            'solicitante': 'Solicitante',
            'tipo': tipo.pk,
            'subatencion': sub.pk,
            'descripcion': 'Descripción',
        }

    def test_formulario_expone_categorias_generales_y_locales_sin_ajenas(self):
        form = self.formulario()
        tipos = form.fields['tipo'].queryset

        self.assertIn(self.tipo_general, tipos)
        self.assertIn(self.tipo_a, tipos)
        self.assertNotIn(self.tipo_b, tipos)
        self.assertNotIn(self.tipo_inactive, tipos)

    def test_categoria_general_admite_subcategorias_generales_y_locales_de_su_delegacion(self):
        form = self.formulario()
        subs = form.fields['subatencion'].queryset

        self.assertIn(self.sub_general, subs)
        self.assertIn(self.sub_a, subs)
        self.assertNotIn(self.sub_b, subs)
        self.assertNotIn(self.sub_inactive, subs)
        self.assertNotIn(self.tipo_inactive_sub, subs)

    def test_categoria_territorial_solo_admite_subcategoria_de_la_misma_delegacion(self):
        form = self.formulario(
            data=self.datos(self.tipo_a, self.sub_a_local),
        )

        self.assertIn(self.sub_a_local, form.fields['subatencion'].queryset)
        self.assertTrue(form.is_valid(), form.errors)

    def test_post_manipulado_con_categoria_ajena_o_subcategoria_incompatible_se_rechaza(self):
        casos = (
            self.datos(self.tipo_b, self.sub_b),
            self.datos(self.tipo_general, self.sub_b),
            self.datos(self.tipo_a, self.sub_general),
        )
        for datos in casos:
            with self.subTest(tipo=datos['tipo'], sub=datos['subatencion']):
                form = self.formulario(datos)
                self.assertFalse(form.is_valid())

    def test_categoria_o_subcategoria_inactiva_no_es_seleccionable(self):
        for datos in (
            self.datos(self.tipo_inactive, self.tipo_inactive_sub),
            self.datos(self.tipo_general, self.sub_inactive),
        ):
            with self.subTest(datos=datos):
                form = self.formulario(datos)
                self.assertFalse(form.is_valid())

    def test_actividad_historica_conserva_las_relaciones_al_deshabilitar_catalogo(self):
        sub = self.sub_a_local
        actividad = AtencionCiudadana.objects.create(
            titulo='Histórica',
            fecha='2026-10-25',
            solicitante='Solicitante histórico',
            tipo=self.tipo_a,
            subatencion=sub,
            descripcion='Actividad histórica',
            delegacion=self.delegacion_a,
            responsable=self.user,
        )
        self.tipo_a.activo = False
        self.tipo_a.save(update_fields=['activo'])
        sub.activo = False
        sub.save(update_fields=['activo'])

        actividad.refresh_from_db()
        self.assertEqual(actividad.tipo_id, self.tipo_a.pk)
        self.assertEqual(actividad.subatencion_id, sub.pk)


class SolicitudCatalogoGeneralTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='SOL-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='SOL-B', nombre='Delegación B')
        self.roles = {}
        self.users = {}
        for codigo in ('administrador', 'coordinador', 'delegado', 'funcionario', 'verificador'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol
            user = User.objects.create_user(username=f'solicitud-{codigo}', password='clave-segura')
            perfil = Perfil.objects.get(usuario=user)
            perfil.rol = rol
            perfil.delegacion = self.delegacion_a
            perfil.save()
            perfil.delegaciones.set([self.delegacion_a])
            self.users[codigo] = user
        self.categoria_general = TipoAtencion.objects.create(
            codigo='SOL-PADRE-G',
            nombre='Categoría general existente',
        )
        self.categoria_local = TipoAtencion.objects.create(
            codigo='SOL-PADRE-A',
            nombre='Categoría local',
            es_general=False,
            delegacion=self.delegacion_a,
        )

    def login(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = ('global' if user == self.users['administrador'] and delegacion is None
                                         else (delegacion or self.delegacion_a).pk)
        session.save()

    def crear_solicitud_categoria(self, solicitante, codigo='NUEVA-GENERAL'):
        self.login(solicitante)
        respuesta = self.client.post(
            reverse('catalogos:solicitud_categoria'),
            {
                'codigo': codigo,
                'nombre': f'Nombre {codigo}',
                'descripcion': 'Descripción solicitada',
            },
        )
        return respuesta, SolicitudCatalogoGeneral.objects.get(codigo=codigo)

    def crear_solicitud_subcategoria(
        self,
        solicitante,
        codigo='NUEVA-SUB-GENERAL',
        padre=None,
    ):
        self.login(solicitante)
        return self.client.post(
            reverse('catalogos:solicitud_subcategoria'),
            {
                'codigo': codigo,
                'nombre': f'Nombre {codigo}',
                'descripcion': 'Descripción solicitada',
                'categoria_padre': (padre or self.categoria_general).pk,
            },
        )

    def decidir(self, accion, solicitud, administrador=None):
        self.login(administrador or self.users['administrador'])
        return self.client.post(
            reverse('catalogos:solicitud_decision', args=[solicitud.pk]),
            {'accion': accion, 'motivo_decision': 'Decisión administrativa'},
        )

    def test_coordinador_y_delegado_pueden_solicitar_categoria_general_pendiente(self):
        for rol in ('coordinador', 'delegado'):
            with self.subTest(rol=rol):
                response, solicitud = self.crear_solicitud_categoria(
                    self.users[rol],
                    codigo=f'SOL-{rol.upper()}',
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)
                self.assertEqual(solicitud.solicitante, self.users[rol])
                self.assertEqual(solicitud.delegacion_solicitante, self.delegacion_a)
                self.assertFalse(
                    TipoAtencion.objects.filter(codigo=solicitud.codigo).exists()
                )

    def test_funcionario_y_verificador_no_pueden_solicitar_catalogos_generales(self):
        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.login(self.users[rol])
                response = self.client.post(
                    reverse('catalogos:solicitud_categoria'),
                    {'codigo': f'DENEGADA-{rol}', 'nombre': 'No permitida'},
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(SolicitudCatalogoGeneral.objects.count(), 0)

    def test_solicitud_pendiente_no_aparece_como_catalogo_utilizable(self):
        _, solicitud = self.crear_solicitud_categoria(self.users['coordinador'])
        self.login(self.users['funcionario'])
        request = RequestFactory().get('/')
        request.user = self.users['funcionario']
        request.session = {'delegacion_activa_id': self.delegacion_a.pk}
        form = AtencionCiudadanaForm(request=request)

        self.assertNotIn(
            solicitud.codigo,
            list(form.fields['tipo'].queryset.values_list('codigo', flat=True)),
        )

    def test_coordinador_y_delegado_no_pueden_aprobar_ni_rechazar_por_post(self):
        _, solicitud = self.crear_solicitud_categoria(self.users['coordinador'])
        for rol in ('coordinador', 'delegado'):
            for accion in ('aprobar', 'rechazar'):
                with self.subTest(rol=rol, accion=accion):
                    self.login(self.users[rol])
                    respuesta = self.client.post(
                        reverse('catalogos:solicitud_decision', args=[solicitud.pk]),
                        {'accion': accion, 'estado': 'aprobada'},
                    )
                    self.assertEqual(respuesta.status_code, 403)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)

    def test_administrador_aprueba_categoria_y_la_publica_como_general(self):
        _, solicitud = self.crear_solicitud_categoria(
            self.users['coordinador'],
            'APROBADA-G',
        )

        respuesta = self.decidir('aprobar', solicitud)

        self.assertEqual(respuesta.status_code, 302)
        solicitud.refresh_from_db()
        categoria = TipoAtencion.objects.get(codigo='APROBADA-G')
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.APROBADA)
        self.assertEqual(solicitud.decidido_por, self.users['administrador'])
        self.assertIsNotNone(solicitud.fecha_decision)
        self.assertTrue(categoria.es_general)
        self.assertIsNone(categoria.delegacion_id)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='aprobar_solicitud_catalogo_general',
                usuario=self.users['administrador'],
                objeto_id=str(solicitud.pk),
            ).exists()
        )

    def test_administrador_rechaza_conservando_solicitud_y_sin_publicarla(self):
        _, solicitud = self.crear_solicitud_categoria(
            self.users['delegado'],
            'RECHAZADA-G',
        )

        respuesta = self.decidir('rechazar', solicitud)

        self.assertEqual(respuesta.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.RECHAZADA)
        self.assertEqual(solicitud.decidido_por, self.users['administrador'])
        self.assertEqual(solicitud.motivo_decision, 'Decisión administrativa')
        self.assertTrue(SolicitudCatalogoGeneral.objects.filter(pk=solicitud.pk).exists())
        self.assertFalse(TipoAtencion.objects.filter(codigo='RECHAZADA-G').exists())
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='rechazar_solicitud_catalogo_general',
                usuario=self.users['administrador'],
                objeto_id=str(solicitud.pk),
            ).exists()
        )

    def test_solicitante_ve_solo_sus_solicitudes_y_administrador_todas(self):
        _, primera = self.crear_solicitud_categoria(
            self.users['coordinador'],
            'VIS-C',
        )
        _, segunda = self.crear_solicitud_categoria(
            self.users['delegado'],
            'VIS-D',
        )

        self.login(self.users['coordinador'])
        propia = self.client.get(reverse('catalogos:solicitud_lista'))
        self.assertContains(propia, primera.codigo)
        self.assertNotContains(propia, segunda.codigo)

        self.login(self.users['funcionario'])
        ajena = self.client.get(reverse('catalogos:solicitud_lista'))
        self.assertEqual(ajena.status_code, 403)

        self.login(self.users['administrador'])
        todas = self.client.get(reverse('catalogos:solicitud_lista'))
        self.assertContains(todas, primera.codigo)
        self.assertContains(todas, segunda.codigo)

    def test_solo_post_decide_y_post_manipulado_no_edita_estado(self):
        _, solicitud = self.crear_solicitud_categoria(self.users['coordinador'])
        self.login(self.users['administrador'])
        get_response = self.client.get(
            reverse('catalogos:solicitud_decision', args=[solicitud.pk])
        )
        self.assertEqual(get_response.status_code, 405)

        self.login(self.users['coordinador'])
        respuesta = self.client.post(
            reverse('catalogos:solicitud_lista'),
            {'estado': 'aprobada'},
        )
        solicitud.refresh_from_db()
        self.assertEqual(respuesta.status_code, 405)
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)

    def test_administrador_conserva_creacion_directa_de_categoria_general(self):
        self.login(self.users['administrador'])

        respuesta = self.client.post(
            reverse('catalogos:tipo_crear'),
            {
                'codigo': 'ADMIN-DIRECTA',
                'nombre': 'Categoría directa',
                'es_general': 'on',
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        categoria = TipoAtencion.objects.get(codigo='ADMIN-DIRECTA')
        self.assertTrue(categoria.es_general)
        self.assertIsNone(categoria.delegacion_id)
        self.assertEqual(SolicitudCatalogoGeneral.objects.count(), 0)

    def test_coordinador_y_delegado_conservan_creacion_territorial(self):
        for rol in ('coordinador', 'delegado'):
            with self.subTest(rol=rol):
                self.login(self.users[rol])
                respuesta = self.client.post(
                    reverse('catalogos:tipo_crear'),
                    {'codigo': f'LOCAL-{rol}', 'nombre': f'Local {rol}'},
                )
                self.assertEqual(respuesta.status_code, 302)
                tipo = TipoAtencion.objects.get(codigo=f'LOCAL-{rol}')
                self.assertFalse(tipo.es_general)
                self.assertEqual(tipo.delegacion, self.delegacion_a)
        self.assertEqual(SolicitudCatalogoGeneral.objects.count(), 0)

    def test_subcategoria_general_se_solicita_y_aprueba_bajo_categoria_general(self):
        for rol in ('coordinador', 'delegado'):
            with self.subTest(rol=rol):
                codigo = f'SUB-SOL-{rol.upper()}'
                respuesta = self.crear_solicitud_subcategoria(
                    self.users[rol],
                    codigo,
                )
                self.assertEqual(respuesta.status_code, 302)
                solicitud = SolicitudCatalogoGeneral.objects.get(
                    nombre=f'Nombre {codigo}'
                )
                self.assertEqual(
                    solicitud.tipo_solicitud,
                    SolicitudCatalogoGeneral.Tipo.SUBCATEGORIA,
                )
                self.assertTrue(solicitud.codigo.startswith('SOL-SUB-'))
                self.assertNotEqual(solicitud.codigo, codigo)
                self.assertEqual(solicitud.categoria_padre, self.categoria_general)
                self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)
                self.assertEqual(self.decidir('aprobar', solicitud).status_code, 302)
                sub = SubAtencion.objects.get(nombre=solicitud.nombre)
                self.assertTrue(sub.es_general)
                self.assertIsNone(sub.delegacion_id)
                self.assertEqual(sub.tipo, self.categoria_general)
                self.assertRegex(sub.codigo, r'^SUB-\d{3,}$')

    def test_subcategoria_general_rechaza_categoria_territorial_por_post_y_modelo(self):
        respuesta = self.crear_solicitud_subcategoria(
            self.users['coordinador'],
            'SUB-PADRE-LOCAL',
            self.categoria_local,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(
            SolicitudCatalogoGeneral.objects.filter(
                nombre='Nombre SUB-PADRE-LOCAL'
            ).exists()
        )
        solicitud_invalida = SolicitudCatalogoGeneral(
            tipo_solicitud=SolicitudCatalogoGeneral.Tipo.SUBCATEGORIA,
            codigo='SUB-MODELO-LOCAL',
            nombre='Sub local no permitida',
            categoria_padre=self.categoria_local,
            solicitante=self.users['coordinador'],
            delegacion_solicitante=self.delegacion_a,
        )
        with self.assertRaises(ValidationError):
            solicitud_invalida.save()

    def test_subcategoria_pendiente_no_aparece_y_aprobada_si(self):
        respuesta = self.crear_solicitud_subcategoria(
            self.users['coordinador'],
            'SUB-PUBLICACION',
        )
        self.assertEqual(respuesta.status_code, 302)
        solicitud = SolicitudCatalogoGeneral.objects.get(
            nombre='Nombre SUB-PUBLICACION'
        )
        self.login(self.users['funcionario'])
        request = RequestFactory().get('/')
        request.user = self.users['funcionario']
        request.session = {'delegacion_activa_id': self.delegacion_a.pk}
        form_pendiente = AtencionCiudadanaForm(request=request)
        self.assertNotIn(
            'SUB-PUBLICACION',
            form_pendiente.fields['subatencion'].queryset.values_list('codigo', flat=True),
        )

        self.decidir('aprobar', solicitud)
        form_aprobada = AtencionCiudadanaForm(request=request)
        publicada = SubAtencion.objects.get(nombre=solicitud.nombre)
        self.assertIn(publicada, form_aprobada.fields['subatencion'].queryset)
        self.assertRegex(publicada.codigo, r'^SUB-\d{3,}$')

    def test_categoria_general_pendiente_debe_aprobarse_antes_de_pedir_subcategoria(self):
        respuesta, solicitud_categoria = self.crear_solicitud_categoria(
            self.users['coordinador'],
            'PADRE-PENDIENTE',
        )
        self.assertEqual(respuesta.status_code, 302)

        self.login(self.users['delegado'])
        solicitud_sub = self.client.post(
            reverse('catalogos:solicitud_subcategoria'),
            {
                'codigo': 'HIJA-PENDIENTE',
                'nombre': 'Hija pendiente',
                'categoria_padre': 9999,
            },
        )

        self.assertEqual(solicitud_sub.status_code, 200)
        self.assertFalse(
            SolicitudCatalogoGeneral.objects.filter(codigo='HIJA-PENDIENTE').exists()
        )

    def test_conflicto_de_codigo_no_sobrescribe_catalogo_y_deja_solicitud_pendiente(self):
        existente = TipoAtencion.objects.create(
            codigo='CODIGO-EN-USO',
            nombre='Catálogo existente',
        )
        _, solicitud = self.crear_solicitud_categoria(
            self.users['coordinador'],
            'CODIGO-EN-USO',
        )

        respuesta = self.decidir('aprobar', solicitud)

        self.assertEqual(respuesta.status_code, 302)
        existente.refresh_from_db()
        solicitud.refresh_from_db()
        self.assertEqual(existente.nombre, 'Catálogo existente')
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)
        self.assertEqual(TipoAtencion.objects.filter(codigo='CODIGO-EN-USO').count(), 1)

    def test_conflicto_de_nombre_general_no_crea_categoria_duplicada(self):
        TipoAtencion.objects.create(
            codigo='NOMBRE-EXISTENTE',
            nombre='Gestión Comunitaria',
        )
        _, solicitud = self.crear_solicitud_categoria(
            self.users['delegado'],
            'NOMBRE-NUEVO-CODIGO',
        )
        solicitud.nombre = 'gestión comunitaria'
        solicitud.save(update_fields=['nombre'])

        respuesta = self.decidir('aprobar', solicitud)

        self.assertEqual(respuesta.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)
        self.assertFalse(
            TipoAtencion.objects.filter(codigo='NOMBRE-NUEVO-CODIGO').exists()
        )

    def test_categoria_padre_inactiva_impide_aprobacion_pero_no_elimina_solicitud(self):
        respuesta = self.crear_solicitud_subcategoria(
            self.users['coordinador'],
            'SUB-PADRE-INACTIVO',
        )
        self.assertEqual(respuesta.status_code, 302)
        solicitud = SolicitudCatalogoGeneral.objects.get(
            nombre='Nombre SUB-PADRE-INACTIVO'
        )
        self.categoria_general.activo = False
        self.categoria_general.save(update_fields=['activo'])

        respuesta_aprobacion = self.decidir('aprobar', solicitud)

        self.assertEqual(respuesta_aprobacion.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.PENDIENTE)
        self.assertFalse(SubAtencion.objects.filter(nombre=solicitud.nombre).exists())
        respuesta_rechazo = self.decidir('rechazar', solicitud)
        self.assertEqual(respuesta_rechazo.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudCatalogoGeneral.Estado.RECHAZADA)

    def test_registros_generales_existentes_siguen_disponibles(self):
        self.login(self.users['funcionario'])
        request = RequestFactory().get('/')
        request.user = self.users['funcionario']
        request.session = {'delegacion_activa_id': self.delegacion_a.pk}
        form = AtencionCiudadanaForm(request=request)

        self.assertIn(self.categoria_general, form.fields['tipo'].queryset)

    def test_navegacion_muestra_solicitudes_a_coordinador_y_delegado(self):
        for rol in ('coordinador', 'delegado'):
            with self.subTest(rol=rol):
                self.login(self.users[rol])
                respuesta = self.client.get(reverse('catalogos:inicio'))
                self.assertContains(
                    respuesta,
                    reverse('catalogos:solicitud_lista'),
                )
                self.assertContains(
                    respuesta,
                    reverse('catalogos:solicitud_categoria'),
                )
                self.assertContains(
                    respuesta,
                    reverse('catalogos:solicitud_subcategoria'),
                )

    def test_creacion_solicitud_queda_auditada(self):
        _, solicitud = self.crear_solicitud_categoria(self.users['delegado'])

        registro = RegistroAuditoria.objects.get(
            accion='crear_solicitud_catalogo_general',
            objeto_id=str(solicitud.pk),
        )
        self.assertEqual(registro.usuario, self.users['delegado'])
        self.assertEqual(registro.modelo, 'catalogos.SolicitudCatalogoGeneral')
