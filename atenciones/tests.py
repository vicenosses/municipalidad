import shutil
import struct
import tempfile
from io import BytesIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from agenda.models import Compromiso
from atenciones.forms import AtencionCiudadanaForm
from atenciones.admin import AtencionCiudadanaAdmin
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from auditoria.models import RegistroAuditoria
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.forms import EvidenciaAtencionForm
from evidencias.models import Evidencia
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


class DelegacionActivaAtencionTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='DEP-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='DEP-B', nombre='Delegación B')
        self.tipo = TipoAtencion.objects.create(codigo='TIP-A', nombre='Tipo A')
        self.subatencion = SubAtencion.objects.create(codigo='SUB-A', nombre='Subatención A', tipo=self.tipo)

        self.coordinador = User.objects.create_user(username='coord', password='segura123')
        self._asignar_perfil(self.coordinador, 'coordinador', self.delegacion_a, [self.delegacion_a, self.delegacion_b])

        self.verificador = User.objects.create_user(username='verif', password='segura123')
        self._asignar_perfil(self.verificador, 'verificador', self.delegacion_a, [self.delegacion_a, self.delegacion_b])

        self.funcionario = User.objects.create_user(username='func', password='segura123')
        self._asignar_perfil(self.funcionario, 'funcionario', self.delegacion_a, [self.delegacion_a, self.delegacion_b])

        self.admin = User.objects.create_superuser(username='admin', email='admin@example.com', password='segura123')

        self.atencion_a = AtencionCiudadana.objects.create(
            titulo='Actividad A',
            fecha='2026-10-20',
            estado=AtencionCiudadana.Estado.REGISTRADA,
            solicitante='Solicitante A',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Atención A',
            delegacion=self.delegacion_a,
            responsable=self.coordinador,
        )
        self.atencion_b = AtencionCiudadana.objects.create(
            titulo='Actividad B',
            fecha='2026-10-21',
            estado=AtencionCiudadana.Estado.EN_PROCESO,
            solicitante='Solicitante B',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Atención B',
            delegacion=self.delegacion_b,
            responsable=self.coordinador,
        )

        self.atencion_func_a = AtencionCiudadana.objects.create(
            titulo='Actividad funcionario A',
            fecha='2026-10-22',
            solicitante='Funcionario A',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Func A',
            delegacion=self.delegacion_a,
            responsable=self.funcionario,
        )
        self.atencion_func_b = AtencionCiudadana.objects.create(
            titulo='Actividad funcionario B',
            fecha='2026-10-23',
            solicitante='Funcionario B',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Func B',
            delegacion=self.delegacion_b,
            responsable=self.funcionario,
        )

    def _asignar_perfil(self, usuario, codigo_rol, delegacion, delegaciones):
        perfil, _ = Perfil.objects.get_or_create(usuario=usuario)
        perfil.rol = Rol.objects.get_or_create(
            codigo=codigo_rol,
            defaults={'nombre': codigo_rol.title(), 'permisos': {'atenciones': True}},
        )[0]
        perfil.delegacion = delegacion
        perfil.activo = True
        perfil.save()
        perfil.delegaciones.set(delegaciones)

    def _activar_delegacion(self, usuario, delegacion):
        self.client.force_login(usuario)
        session = self.client.session
        session['delegacion_activa_id'] = delegacion.pk
        session.save()

    def test_coordinador_usa_delegacion_activa_en_listado(self):
        self._activar_delegacion(self.coordinador, self.delegacion_a)
        respuesta = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta, self.atencion_a.solicitante)
        self.assertNotContains(respuesta, self.atencion_b.solicitante)

    def test_coordinador_cambia_delegacion_activa_y_refresca_listado(self):
        self._activar_delegacion(self.coordinador, self.delegacion_a)
        self.client.get(reverse('atenciones:lista'))

        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion_b.pk
        session.save()

        respuesta = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta, self.atencion_b.solicitante)
        self.assertNotContains(respuesta, self.atencion_a.solicitante)

    def test_verificador_respeta_delegacion_activa(self):
        self._activar_delegacion(self.verificador, self.delegacion_b)
        respuesta = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta, self.atencion_b.solicitante)
        self.assertNotContains(respuesta, self.atencion_a.solicitante)

    def test_funcionario_mantiene_comportamiento_existente(self):
        self._activar_delegacion(self.funcionario, self.delegacion_a)
        respuesta = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta, self.atencion_func_a.solicitante)
        self.assertNotContains(respuesta, self.atencion_func_b.solicitante)

    def test_administrador_sigue_viendo_todos_los_registros(self):
        self._activar_delegacion(self.admin, self.delegacion_a)
        self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        respuesta = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta, self.atencion_a.solicitante)
        self.assertContains(respuesta, self.atencion_b.solicitante)

    def test_usuario_sin_delegacion_activa_no_ve_actividades_por_ser_responsable(self):
        self.funcionario.perfil.delegaciones.clear()
        self._activar_delegacion(self.funcionario, self.delegacion_a)

        listado = self.client.get(reverse('atenciones:lista'))
        detalle = self.client.get(
            reverse('atenciones:detalle', args=[self.atencion_func_a.pk])
        )

        self.assertNotContains(listado, self.atencion_func_a.solicitante)
        self.assertEqual(detalle.status_code, 404)

    def test_delegacion_inactiva_corta_acceso_a_actividades(self):
        self.delegacion_a.activa = False
        self.delegacion_a.save(update_fields=['activa'])
        self._activar_delegacion(self.funcionario, self.delegacion_a)

        listado = self.client.get(reverse('atenciones:lista'))
        detalle = self.client.get(
            reverse('atenciones:detalle', args=[self.atencion_func_a.pk])
        )

        self.assertNotContains(listado, self.atencion_func_a.solicitante)
        self.assertEqual(detalle.status_code, 404)

    def test_delegacion_no_autorizada_corta_acceso_aunque_sea_responsable(self):
        self.funcionario.perfil.delegaciones.remove(self.delegacion_a)
        self._activar_delegacion(self.funcionario, self.delegacion_a)

        listado = self.client.get(reverse('atenciones:lista'))
        detalle = self.client.get(
            reverse('atenciones:detalle', args=[self.atencion_func_a.pk])
        )

        self.assertNotContains(listado, self.atencion_func_a.solicitante)
        self.assertEqual(detalle.status_code, 404)


class AtencionEstadoPermissionsTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='EST-A', nombre='Estado A')
        self.delegacion_b = Delegacion.objects.create(codigo='EST-B', nombre='Estado B')
        self.tipo = TipoAtencion.objects.create(codigo='EST-T', nombre='Tipo estado')
        self.subatencion = SubAtencion.objects.create(
            codigo='EST-S',
            nombre='Subatención estado',
            tipo=self.tipo,
        )
        self.users = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            user = User.objects.create_user(username=f'estado-{codigo}', password='clave-segura')
            perfil = Perfil.objects.get(usuario=user)
            perfil.rol = rol
            perfil.delegacion = self.delegacion_a
            perfil.save()
            perfil.delegaciones.set([self.delegacion_a])
            user.perfil = perfil
            self.users[codigo] = user
        self.admin = User.objects.create_superuser(
            username='estado-admin-root',
            email='estado-admin@example.com',
            password='clave-segura',
        )

    def crear_actividad(
        self,
        titulo,
        *,
        delegacion=None,
        estado=AtencionCiudadana.Estado.REGISTRADA,
        creador=None,
    ):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            estado=estado,
            solicitante=titulo,
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion=titulo,
            delegacion=delegacion or self.delegacion_a,
            responsable=creador or self.users['funcionario'],
            creado_por=creador or self.users['funcionario'],
        )

    def activar(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = (delegacion or self.delegacion_a).pk
        session.save()

    def cambiar(self, user, actividad, estado, **post_extra):
        self.activar(user)
        if user == self.admin:
            self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        return self.client.post(
            reverse('atenciones:cambiar_estado', args=[actividad.pk]),
            {'estado': estado, **post_extra},
        )

    def afirmar_transicion(self, user, actividad, estado_nuevo):
        respuesta = self.cambiar(user, actividad, estado_nuevo)
        self.assertEqual(respuesta.status_code, 302)
        actividad.refresh_from_db()
        self.assertEqual(actividad.estado, estado_nuevo)

    def afirmar_rechazo(self, user, actividad, estado_nuevo, status=404):
        respuesta = self.cambiar(user, actividad, estado_nuevo)
        self.assertEqual(respuesta.status_code, status)
        actividad.refresh_from_db()
        self.assertNotEqual(actividad.estado, estado_nuevo)

    def test_funcionario_creador_avanza_secuencialmente_y_no_reabre(self):
        actividad = self.crear_actividad(
            'Actividad funcionario',
            creador=self.users['funcionario'],
        )
        self.afirmar_transicion(
            self.users['funcionario'],
            actividad,
            AtencionCiudadana.Estado.EN_PROCESO,
        )
        self.afirmar_transicion(
            self.users['funcionario'],
            actividad,
            AtencionCiudadana.Estado.CERRADA,
        )
        self.afirmar_rechazo(
            self.users['funcionario'],
            actividad,
            AtencionCiudadana.Estado.EN_PROCESO,
        )

    def test_funcionario_no_salta_estados_ni_modifica_actividad_ajena(self):
        actividad = self.crear_actividad('Actividad para transición')
        self.afirmar_rechazo(
            self.users['funcionario'],
            actividad,
            AtencionCiudadana.Estado.CERRADA,
        )
        otra = self.crear_actividad(
            'Actividad de otro creador',
            creador=self.users['delegado'],
        )
        self.afirmar_rechazo(
            self.users['funcionario'],
            otra,
            AtencionCiudadana.Estado.EN_PROCESO,
        )

    def test_ningun_rol_puede_saltar_de_registrada_a_cerrada(self):
        for codigo in ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario'):
            with self.subTest(rol=codigo):
                actividad = self.crear_actividad(f'Salto prohibido {codigo}')
                user = (
                    self.admin
                    if codigo == 'administrador'
                    else self.users[codigo]
                )
                self.afirmar_rechazo(
                    user,
                    actividad,
                    AtencionCiudadana.Estado.CERRADA,
                )

    def test_verificador_creador_avanza_pero_no_reabre_ni_edita_actividad_ajena(self):
        propia = self.crear_actividad(
            'Actividad verificador',
            creador=self.users['verificador'],
        )
        self.afirmar_transicion(
            self.users['verificador'],
            propia,
            AtencionCiudadana.Estado.EN_PROCESO,
        )
        self.afirmar_transicion(
            self.users['verificador'],
            propia,
            AtencionCiudadana.Estado.CERRADA,
        )
        self.afirmar_rechazo(
            self.users['verificador'],
            propia,
            AtencionCiudadana.Estado.EN_PROCESO,
        )
        ajena = self.crear_actividad(
            'Actividad ajena a verificador',
            creador=self.users['delegado'],
        )
        self.afirmar_rechazo(
            self.users['verificador'],
            ajena,
            AtencionCiudadana.Estado.EN_PROCESO,
        )

    def test_coordinador_y_delegado_gestionan_y_reabren_solo_en_su_delegacion(self):
        for codigo in ('coordinador', 'delegado'):
            with self.subTest(rol=codigo):
                user = self.users[codigo]
                actividad = self.crear_actividad(
                    f'Actividad {codigo}',
                    estado=AtencionCiudadana.Estado.CERRADA,
                )
                self.afirmar_transicion(
                    user,
                    actividad,
                    AtencionCiudadana.Estado.EN_PROCESO,
                )
                self.afirmar_transicion(
                    user,
                    actividad,
                    AtencionCiudadana.Estado.CERRADA,
                )
                otra = self.crear_actividad(
                    f'Actividad otra delegación {codigo}',
                    delegacion=self.delegacion_b,
                )
                self.afirmar_rechazo(
                    user,
                    otra,
                    AtencionCiudadana.Estado.EN_PROCESO,
                )

    def test_administrador_puede_gestionar_y_reabrir_globalmente(self):
        actividad = self.crear_actividad(
            'Actividad global',
            delegacion=self.delegacion_b,
            estado=AtencionCiudadana.Estado.CERRADA,
        )
        self.afirmar_transicion(
            self.admin,
            actividad,
            AtencionCiudadana.Estado.EN_PROCESO,
        )
        self.afirmar_transicion(
            self.admin,
            actividad,
            AtencionCiudadana.Estado.CERRADA,
        )

    def test_post_no_cambia_delegacion_ni_creador_y_audita_estado(self):
        creador = self.users['funcionario']
        actividad = self.crear_actividad('Actividad inmutable', creador=creador)
        otro_usuario = self.users['coordinador']
        self.activar(creador)

        respuesta = self.client.post(
            reverse('atenciones:cambiar_estado', args=[actividad.pk]),
            {
                'estado': AtencionCiudadana.Estado.EN_PROCESO,
                'delegacion': self.delegacion_b.pk,
                'creado_por': otro_usuario.pk,
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        actividad.refresh_from_db()
        self.assertEqual(actividad.estado, AtencionCiudadana.Estado.EN_PROCESO)
        self.assertEqual(actividad.delegacion, self.delegacion_a)
        self.assertEqual(actividad.creado_por, creador)
        from auditoria.models import RegistroAuditoria

        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='cambiar_estado',
                modelo='atenciones.AtencionCiudadana',
                objeto_id=str(actividad.pk),
                usuario=creador,
            ).exists()
        )

    def test_botones_reflejan_transiciones_permitidas(self):
        actividad = self.crear_actividad(
            'Actividad propia para botones',
            creador=self.users['funcionario'],
        )
        self.activar(self.users['funcionario'])
        lista = self.client.get(reverse('atenciones:lista'))
        detalle = self.client.get(reverse('atenciones:detalle', args=[actividad.pk]))
        self.assertContains(lista, 'Cambiar a En proceso')
        self.assertContains(detalle, 'Pasar a En proceso')
        self.assertNotContains(lista, 'Cerrar actividad')

        actividad.estado = AtencionCiudadana.Estado.CERRADA
        actividad.save(update_fields=['estado'])
        lista = self.client.get(reverse('atenciones:lista'))
        self.assertNotContains(lista, 'Reabrir actividad')


class AtencionDisponibilidadTests(TestCase):
    def setUp(self):
        self.directorio_media = tempfile.mkdtemp(prefix='actividad-disponibilidad-')
        override = override_settings(MEDIA_ROOT=self.directorio_media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.directorio_media, ignore_errors=True)

        self.delegacion_a = Delegacion.objects.create(codigo='DIS-A', nombre='Disponibilidad A')
        self.delegacion_b = Delegacion.objects.create(codigo='DIS-B', nombre='Disponibilidad B')
        self.tipo = TipoAtencion.objects.create(codigo='DIS-T', nombre='Tipo disponibilidad')
        self.subatencion = SubAtencion.objects.create(
            codigo='DIS-S',
            nombre='Subatención disponibilidad',
            tipo=self.tipo,
        )
        self.users = {}
        for codigo in ('delegado', 'coordinador', 'verificador', 'funcionario'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            user = User.objects.create_user(
                username=f'disponibilidad-{codigo}',
                password='clave-segura',
            )
            perfil = Perfil.objects.get(usuario=user)
            perfil.rol = rol
            perfil.delegacion = self.delegacion_a
            perfil.save()
            perfil.delegaciones.set([self.delegacion_a])
            user.perfil = perfil
            self.users[codigo] = user
        self.admin = User.objects.create_superuser(
            username='disponibilidad-admin',
            email='disponibilidad-admin@example.com',
            password='clave-segura',
        )
        self.actividad = self.crear_actividad('Actividad habilitada')

    def crear_actividad(self, titulo, delegacion=None):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            solicitante=titulo,
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion=titulo,
            delegacion=delegacion or self.delegacion_a,
            responsable=self.users['funcionario'],
            creado_por=self.users['funcionario'],
        )

    def iniciar_sesion(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = (delegacion or self.delegacion_a).pk
        session.save()

    def cambiar_disponibilidad(self, user, actividad, habilitada, **extra):
        self.iniciar_sesion(user)
        if user == self.admin:
            self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        return self.client.post(
            reverse('atenciones:cambiar_disponibilidad', args=[actividad.pk]),
            {'activo': 'true' if habilitada else 'false', **extra},
        )

    def test_registros_existentes_y_nuevas_actividades_quedan_habilitadas(self):
        self.assertTrue(self.actividad.activo)
        nueva = self.client
        self.iniciar_sesion(self.users['funcionario'])
        response = nueva.post(
            reverse('atenciones:crear'),
            {
                'titulo': 'Nueva actividad habilitada',
                'fecha': '2026-10-25',
                'estado': AtencionCiudadana.Estado.REGISTRADA,
                'solicitante': 'Solicitante',
                'tipo': self.tipo.pk,
                'subatencion': self.subatencion.pk,
                'descripcion': 'Descripción',
            },
        )
        self.assertEqual(response.status_code, 302)
        actividad = AtencionCiudadana.objects.get(titulo='Nueva actividad habilitada')
        self.assertTrue(actividad.activo)

    def test_delegado_deshabilita_y_habilita_actividad_propia(self):
        deshabilitar = self.cambiar_disponibilidad(
            self.users['delegado'],
            self.actividad,
            False,
        )
        self.assertEqual(deshabilitar.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertFalse(self.actividad.activo)
        self.assertTrue(AtencionCiudadana.objects.filter(pk=self.actividad.pk).exists())

        habilitar = self.cambiar_disponibilidad(
            self.users['delegado'],
            self.actividad,
            True,
        )
        self.assertEqual(habilitar.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertTrue(self.actividad.activo)

    def test_delegado_no_puede_cambiar_disponibilidad_fuera_de_delegacion(self):
        ajena = self.crear_actividad('Actividad ajena', self.delegacion_b)
        response = self.cambiar_disponibilidad(
            self.users['delegado'],
            ajena,
            False,
            delegacion=self.delegacion_b.pk,
        )
        self.assertEqual(response.status_code, 404)
        ajena.refresh_from_db()
        self.assertTrue(ajena.activo)

    def test_administrador_cambia_disponibilidad_globalmente(self):
        ajena = self.crear_actividad('Actividad global', self.delegacion_b)
        for habilitada in (False, True):
            response = self.cambiar_disponibilidad(
                self.admin,
                ajena,
                habilitada,
                delegacion=self.delegacion_a.pk,
            )
            self.assertEqual(response.status_code, 302)
            ajena.refresh_from_db()
            self.assertEqual(ajena.activo, habilitada)

    def test_coordinador_funcionario_y_verificador_no_pueden_habilitar_ni_deshabilitar(self):
        for codigo in ('coordinador', 'funcionario', 'verificador'):
            with self.subTest(rol=codigo):
                for habilitada in (False, True):
                    response = self.cambiar_disponibilidad(
                        self.users[codigo],
                        self.actividad,
                        habilitada,
                    )
                    self.assertEqual(response.status_code, 403)
                    self.actividad.refresh_from_db()
                    self.assertTrue(self.actividad.activo)

    def test_post_manipulado_no_elude_alcance_y_get_no_cambia_datos(self):
        ajena = self.crear_actividad('Actividad ajena manipulada', self.delegacion_b)
        self.iniciar_sesion(self.users['delegado'])

        get_response = self.client.get(
            reverse('atenciones:cambiar_disponibilidad', args=[self.actividad.pk])
        )
        post_response = self.client.post(
            reverse('atenciones:cambiar_disponibilidad', args=[ajena.pk]),
            {'activo': 'false', 'delegacion': self.delegacion_a.pk},
        )

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(post_response.status_code, 404)
        self.actividad.refresh_from_db()
        ajena.refresh_from_db()
        self.assertTrue(self.actividad.activo)
        self.assertTrue(ajena.activo)

    def test_deshabilitar_conserva_evidencias_y_relaciones_de_agenda(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso relacionado',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.users['funcionario'],
            delegacion=self.delegacion_a,
        )
        compromiso.actividades.add(self.actividad)
        evidencia = Evidencia.objects.create(
            atencion=self.actividad,
            archivo='evidencias/historica.png',
            subido_por=self.users['funcionario'],
        )

        response = self.cambiar_disponibilidad(
            self.users['delegado'],
            self.actividad,
            False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AtencionCiudadana.objects.filter(pk=self.actividad.pk).exists())
        self.assertTrue(Evidencia.objects.filter(pk=evidencia.pk, atencion=self.actividad).exists())
        self.assertTrue(compromiso.actividades.filter(pk=self.actividad.pk).exists())

    def test_actividad_deshabilitada_es_visible_en_listado_y_detalle(self):
        self.actividad.activo = False
        self.actividad.save(update_fields=['activo'])
        self.iniciar_sesion(self.users['delegado'])

        listado = self.client.get(reverse('atenciones:lista'))
        detalle = self.client.get(reverse('atenciones:detalle', args=[self.actividad.pk]))

        self.assertContains(listado, self.actividad.titulo)
        self.assertContains(listado, 'Deshabilitada')
        self.assertContains(detalle, self.actividad.titulo)
        self.assertContains(detalle, 'Deshabilitada')

    def test_actividad_deshabilitada_no_puede_cambiar_estado_y_rehabilitada_si(self):
        self.actividad.activo = False
        self.actividad.save(update_fields=['activo'])
        self.iniciar_sesion(self.users['delegado'])
        bloqueado = self.client.post(
            reverse('atenciones:cambiar_estado', args=[self.actividad.pk]),
            {'estado': AtencionCiudadana.Estado.EN_PROCESO},
        )
        self.assertEqual(bloqueado.status_code, 404)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, AtencionCiudadana.Estado.REGISTRADA)

        self.cambiar_disponibilidad(self.users['delegado'], self.actividad, True)
        permitido = self.client.post(
            reverse('atenciones:cambiar_estado', args=[self.actividad.pk]),
            {'estado': AtencionCiudadana.Estado.EN_PROCESO},
        )
        self.assertEqual(permitido.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, AtencionCiudadana.Estado.EN_PROCESO)

    def test_actividad_deshabilitada_no_acepta_evidencias_y_rehabilitada_si(self):
        self.actividad.activo = False
        self.actividad.save(update_fields=['activo'])
        self.iniciar_sesion(self.users['funcionario'])
        url = reverse('evidencias:atencion_crear', args=[self.actividad.pk])

        bloqueada = self.client.post(url, {'archivos': [imagen_valida()]})

        self.assertEqual(bloqueada.status_code, 404)
        self.assertFalse(Evidencia.objects.filter(atencion=self.actividad).exists())
        self.cambiar_disponibilidad(self.users['delegado'], self.actividad, True)
        self.iniciar_sesion(self.users['funcionario'])
        permitida = self.client.post(url, {'archivos': [imagen_valida()]})
        self.assertEqual(permitida.status_code, 302)
        self.assertTrue(Evidencia.objects.filter(atencion=self.actividad).exists())

    def test_actividad_cerrada_habilitada_sigue_bloqueando_evidencia(self):
        self.actividad.estado = AtencionCiudadana.Estado.CERRADA
        self.actividad.save(update_fields=['estado'])
        self.iniciar_sesion(self.users['funcionario'])
        response = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.actividad.pk]),
            {'archivos': [imagen_valida()]},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Evidencia.objects.filter(atencion=self.actividad).exists())

    def test_boton_disponibilidad_solo_aparece_a_delegado_o_administrador(self):
        for codigo in ('funcionario', 'verificador', 'coordinador'):
            with self.subTest(rol=codigo):
                self.iniciar_sesion(self.users[codigo])
                response = self.client.get(reverse('atenciones:lista'))
                self.assertNotContains(response, 'Deshabilitar')
                self.assertNotContains(response, 'Habilitar')

        self.iniciar_sesion(self.users['delegado'])
        delegado = self.client.get(reverse('atenciones:lista'))
        self.assertContains(delegado, 'Deshabilitar')

        self.iniciar_sesion(self.admin)
        administrador = self.client.get(reverse('atenciones:lista'))
        self.assertContains(administrador, 'Deshabilitar')

    def test_auditoria_registra_deshabilitacion_y_rehabilitacion(self):
        user = self.users['delegado']
        for habilitada, accion in ((False, 'deshabilitar'), (True, 'habilitar')):
            response = self.cambiar_disponibilidad(user, self.actividad, habilitada)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(
                RegistroAuditoria.objects.filter(
                    usuario=user,
                    accion=accion,
                    modelo='atenciones.AtencionCiudadana',
                    objeto_id=str(self.actividad.pk),
                ).exists()
            )

    def test_admin_no_puede_borrar_ni_editar_campos_protegidos(self):
        model_admin = AtencionCiudadanaAdmin(AtencionCiudadana, admin.site)
        request = type('Request', (), {'user': self.admin})()
        readonly_activa = model_admin.get_readonly_fields(request, self.actividad)
        deshabilitada = self.actividad
        deshabilitada.activo = False
        readonly_deshabilitada = model_admin.get_readonly_fields(request, deshabilitada)

        self.assertIn('creado_por', readonly_activa)
        self.assertIn('delegacion', readonly_activa)
        self.assertIn('estado', readonly_activa)
        self.assertIn('activo', readonly_activa)
        self.assertCountEqual(
            readonly_deshabilitada,
            [
                field.name
                for field in self.actividad._meta.fields
                if not field.primary_key
            ],
        )
        self.assertFalse(model_admin.has_delete_permission(request, self.actividad))


def imagen_valida(extension='png', formato='PNG'):
    contenido = BytesIO()
    Image.new('RGB', (3, 3), color='red').save(contenido, format=formato)
    return SimpleUploadedFile(
        f'evidencia.{extension}',
        contenido.getvalue(),
        content_type=f'image/{extension if extension != "jpg" else "jpeg"}',
    )


def mp4_valido():
    contenido = (
        struct.pack('>I4s4sI', 16, b'ftyp', b'isom', 0)
        + struct.pack('>I4s', 8, b'moov')
        + struct.pack('>I4s', 9, b'mdat')
        + b'\x00'
    )
    return SimpleUploadedFile('clip.mp4', contenido, content_type='video/mp4')


def webm_valido():
    contenido = (
        b'\x1a\x45\xdf\xa3'
        b'\x42\x82\x84webm'
        b'\x18\x53\x80\x67'
        b'\x16\x54\xae\x6b'
        b'\x1f\x43\xb6\x75'
    )
    return SimpleUploadedFile('clip.webm', contenido, content_type='video/webm')


class EvidenciaAtencionTests(TestCase):
    def setUp(self):
        self.directorio_media = tempfile.mkdtemp(prefix='sgr-test-media-')
        self.override_media = override_settings(MEDIA_ROOT=self.directorio_media)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.addCleanup(shutil.rmtree, self.directorio_media, ignore_errors=True)

        self.delegacion = Delegacion.objects.create(codigo='TEST-1', nombre='Delegación de prueba')
        self.tipo = TipoAtencion.objects.create(codigo='TEST-T', nombre='Tipo de prueba')
        self.subtipo = SubAtencion.objects.create(
            codigo='TEST-S',
            nombre='Subatención de prueba',
            tipo=self.tipo,
        )
        self.creador = User.objects.create_user(username='vicente.test', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.creador)
        perfil.delegacion = self.delegacion
        perfil.save(update_fields=['delegacion'])
        perfil.delegaciones.add(self.delegacion)
        self.atencion = AtencionCiudadana.objects.create(
            titulo='Actividad de prueba',
            fecha='2026-10-24',
            estado=AtencionCiudadana.Estado.REGISTRADA,
            solicitante='Persona de prueba',
            tipo=self.tipo,
            subatencion=self.subtipo,
            descripcion='Atención de prueba',
            delegacion=self.delegacion,
            responsable=self.creador,
        )
        self.client.force_login(self.creador)

    def test_listado_muestra_acciones_juntas_y_solo_al_creador(self):
        self.assertIsNone(self.atencion.creado_por)
        respuesta = self.client.get(reverse('atenciones:lista'))

        self.assertContains(respuesta, reverse('atenciones:detalle', args=[self.atencion.pk]))
        self.assertContains(respuesta, reverse('evidencias:atencion_crear', args=[self.atencion.pk]))
        self.assertContains(respuesta, self.atencion.titulo)
        self.assertContains(respuesta, self.atencion.get_estado_display())
        html = respuesta.content.decode()
        self.assertLess(html.index('>Ver</a>'), html.index('>Agregar evidencia</a>'))

        detalle = self.client.get(reverse('atenciones:detalle', args=[self.atencion.pk]))
        self.assertContains(detalle, self.atencion.titulo)
        self.assertContains(detalle, 'Fecha de actividad:')
        self.assertContains(detalle, self.atencion.get_estado_display())

        otro = User.objects.create_user(username='otro.usuario', password='clave-segura')
        perfil_otro = Perfil.objects.get(usuario=otro)
        perfil_otro.rol = Rol.objects.get(codigo='coordinador')
        perfil_otro.delegacion = self.delegacion
        perfil_otro.save()
        perfil_otro.delegaciones.add(self.delegacion)
        self.client.force_login(otro)
        respuesta_otro = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta_otro, self.atencion.solicitante)
        self.assertNotContains(respuesta_otro, 'Agregar evidencia')

    def test_creacion_ignora_estado_manipulado_y_guarda_va_al_tubo(self):
        otro_usuario = User.objects.create_user(
            username='creador-manipulado',
            password='clave-segura',
        )
        for estado in (
            AtencionCiudadana.Estado.CERRADA,
            AtencionCiudadana.Estado.EN_PROCESO,
        ):
            with self.subTest(estado=estado):
                titulo = f'Actividad nueva {estado}'
                respuesta = self.client.post(
                    reverse('atenciones:crear'),
                    {
                        'titulo': titulo,
                        'fecha': '2026-10-24',
                        'estado': estado,
                        'solicitante': 'Persona nueva',
                        'tipo': self.tipo.pk,
                        'subatencion': self.subtipo.pk,
                        'va_al_tubo': 'on',
                        'descripcion': 'Atención con tubo activo',
                        'creado_por': otro_usuario.pk,
                    },
                )

                self.assertEqual(respuesta.status_code, 302)
                actividad = AtencionCiudadana.objects.get(titulo=titulo)
                self.assertEqual(actividad.fecha.isoformat(), '2026-10-24')
                self.assertEqual(actividad.estado, AtencionCiudadana.Estado.REGISTRADA)
                self.assertTrue(actividad.va_al_tubo)
                self.assertEqual(actividad.delegacion, self.delegacion)
                self.assertEqual(actividad.responsable, self.creador)
                self.assertEqual(actividad.creado_por, self.creador)

    def test_formulario_de_edicion_no_cambia_creador(self):
        otro_usuario = User.objects.create_user(
            username='creador-ajeno',
            password='clave-segura',
        )
        self.atencion.creado_por = self.creador
        self.atencion.save(update_fields=['creado_por'])
        form = AtencionCiudadanaForm(
            data={
                'titulo': 'Actividad editada',
                'fecha': '2026-10-25',
                'estado': AtencionCiudadana.Estado.EN_PROCESO,
                'solicitante': self.atencion.solicitante,
                'tipo': self.tipo.pk,
                'subatencion': self.subtipo.pk,
                'va_al_tubo': '',
                'descripcion': self.atencion.descripcion,
                'creado_por': otro_usuario.pk,
            },
            instance=self.atencion,
        )

        self.assertNotIn('creado_por', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        actividad = form.save()
        self.assertEqual(actividad.creado_por, self.creador)

    def test_creador_puede_eliminarse_sin_eliminar_actividad_historica(self):
        responsable = User.objects.create_user(
            username='responsable-historico',
            password='clave-segura',
        )
        self.atencion.creado_por = self.creador
        self.atencion.responsable = responsable
        self.atencion.save(update_fields=['creado_por', 'responsable'])

        self.creador.delete()

        self.atencion.refresh_from_db()
        self.assertIsNone(self.atencion.creado_por)
        self.assertEqual(self.atencion.responsable, responsable)
        self.assertTrue(AtencionCiudadana.objects.filter(pk=self.atencion.pk).exists())

    def test_subatencion_fuera_de_tipo_se_rechaza_en_backend(self):
        otro_tipo = TipoAtencion.objects.create(codigo='OTRO-T', nombre='Tipo ajeno')
        otra_sub = SubAtencion.objects.create(codigo='OTRO-S', nombre='Subatención ajena', tipo=otro_tipo)

        form = AtencionCiudadanaForm(
            data={
                'titulo': 'Actividad ajena',
                'fecha': '2026-10-24',
                'estado': AtencionCiudadana.Estado.REGISTRADA,
                'solicitante': 'Persona ajena',
                'tipo': self.tipo.pk,
                'subatencion': otra_sub.pk,
                'va_al_tubo': True,
                'descripcion': 'Subatención incorrecta',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('subatencion', form.errors)

    def test_formulario_requiere_titulo_y_fecha_sin_exponer_estado(self):
        form = AtencionCiudadanaForm(data={
            'solicitante': 'Persona nueva',
            'tipo': self.tipo.pk,
            'subatencion': self.subtipo.pk,
            'va_al_tubo': False,
            'descripcion': 'Descripción',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('titulo', form.errors)
        self.assertIn('fecha', form.errors)
        self.assertNotIn('estado', form.fields)

    def test_creador_puede_subir_imagen_y_video_en_el_mismo_envio(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {
                'archivos': [
                    imagen_valida(),
                    imagen_valida('jpg', 'JPEG'),
                    imagen_valida('webp', 'WEBP'),
                    mp4_valido(),
                ]
            },
        )

        self.assertRedirects(respuesta, reverse('atenciones:detalle', args=[self.atencion.pk]))
        evidencias = list(Evidencia.objects.filter(atencion=self.atencion).order_by('tipo_archivo'))
        self.assertEqual(len(evidencias), 4)
        self.assertEqual({e.tipo_archivo for e in evidencias}, {'imagen', 'video'})
        self.assertTrue(all(e.estado == Evidencia.Estado.PENDIENTE for e in evidencias))
        self.assertTrue(all(e.subido_por == self.creador for e in evidencias))
        self.assertEqual(len({e.identificador for e in evidencias}), 4)
        prefijo = f'{timezone.localtime().strftime("%Y%m%d")}_vicentetest_'
        self.assertTrue(all(e.identificador.startswith(prefijo) for e in evidencias))

    def test_creador_puede_subir_video_webm(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {'archivos': [webm_valido()]},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Evidencia.objects.get().tipo_archivo, 'video')

    def test_actividad_cerrada_bloquea_evidencia_y_reabierta_la_permite(self):
        rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        perfil = Perfil.objects.get(usuario=self.creador)
        perfil.rol = rol
        perfil.save(update_fields=['rol'])
        self.atencion.creado_por = self.creador
        self.atencion.estado = AtencionCiudadana.Estado.CERRADA
        self.atencion.save(update_fields=['creado_por', 'estado'])
        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion.pk
        session.save()
        url = reverse('evidencias:atencion_crear', args=[self.atencion.pk])

        cerrada = self.client.post(url, {'archivos': [imagen_valida()]})

        self.assertEqual(cerrada.status_code, 404)
        self.assertFalse(Evidencia.objects.filter(atencion=self.atencion).exists())

        self.atencion.estado = AtencionCiudadana.Estado.EN_PROCESO
        self.atencion.save(update_fields=['estado'])
        reabierta = self.client.post(url, {'archivos': [imagen_valida()]})

        self.assertEqual(reabierta.status_code, 302)
        self.assertTrue(Evidencia.objects.filter(atencion=self.atencion).exists())

    def test_otro_usuario_no_puede_abrir_formulario_ni_enviar_archivos(self):
        otro = User.objects.create_user(username='otro.usuario', password='clave-segura')
        self.client.force_login(otro)
        url = reverse('evidencias:atencion_crear', args=[self.atencion.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        respuesta = self.client.post(url, {'archivos': [imagen_valida()]})
        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(Evidencia.objects.exists())

    def test_archivos_invalidos_y_demasiado_grandes_se_rechazan(self):
        archivo_falso = SimpleUploadedFile(
            'falso.png',
            b'no es una imagen',
            content_type='image/png',
        )
        form_falso = EvidenciaAtencionForm(files={'archivos': [archivo_falso]})
        self.assertFalse(form_falso.is_valid())

        tipo_falso = SimpleUploadedFile(
            'foto.txt',
            b'contenido',
            content_type='image/png',
        )
        form_tipo = EvidenciaAtencionForm(files={'archivos': [tipo_falso]})
        self.assertFalse(form_tipo.is_valid())

        with override_settings(EVIDENCIA_MAX_IMAGE_MB=0):
            form_grande = EvidenciaAtencionForm(files={'archivos': [imagen_valida()]})
            self.assertFalse(form_grande.is_valid())

        with override_settings(EVIDENCIA_MAX_BATCH_MB=0):
            form_lote = EvidenciaAtencionForm(files={'archivos': [imagen_valida()]})
            self.assertFalse(form_lote.is_valid())

    def test_estado_general_prioriza_rechazado_y_luego_pendiente(self):
        self.assertEqual(self.atencion.estado_evidencias, 'sin_evidencia')
        primera = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/imagen.png',
            subido_por=self.creador,
            estado=Evidencia.Estado.APROBADA,
        )
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'aprobada')
        segunda = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'pendiente')
        segunda.estado = Evidencia.Estado.RECHAZADA
        segunda.save(update_fields=['estado'])
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'rechazada')
        self.assertEqual(primera.estado, Evidencia.Estado.APROBADA)

    def test_administrador_puede_aprobar_y_rechazar_y_cambios_se_reflejan(self):
        aprobado = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/aprobada.png',
            subido_por=self.creador,
        )
        rechazada = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/rechazada.png',
            subido_por=self.creador,
        )
        administrador = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='clave-segura',
        )
        self.client.force_login(administrador)
        lista_admin = self.client.get(reverse('evidencias:lista'))
        self.assertContains(lista_admin, aprobado.identificador)
        self.assertContains(lista_admin, rechazada.identificador)

        self.client.post(
            reverse('evidencias:validar', args=[aprobado.pk]),
            {'accion': 'aprobar', 'comentario': ''},
        )
        self.client.post(
            reverse('evidencias:validar', args=[rechazada.pk]),
            {'accion': 'rechazar', 'comentario': 'Falta contexto'},
        )
        aprobado.refresh_from_db()
        rechazada.refresh_from_db()
        self.atencion.refresh_from_db()

        self.assertEqual(aprobado.estado, Evidencia.Estado.APROBADA)
        self.assertEqual(rechazada.estado, Evidencia.Estado.RECHAZADA)
        self.assertEqual(rechazada.comentario_validacion, 'Falta contexto')
        self.assertEqual(self.atencion.estado_evidencias, 'rechazada')
        detalle = self.client.get(reverse('atenciones:detalle', args=[self.atencion.pk]))
        self.assertContains(detalle, 'Falta contexto')
        self.assertContains(detalle, 'Rechazada')

    def test_archivo_privado_no_se_sirve_a_otro_usuario(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/privada.png',
            subido_por=self.creador,
        )
        otro = User.objects.create_user(username='visitante', password='clave-segura')
        self.client.force_login(otro)

        respuesta = self.client.get(reverse('evidencia_archivo', args=[evidencia.pk]))

        self.assertEqual(respuesta.status_code, 404)

    def test_coordinador_no_puede_validar_evidencia_ciudadana(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        coordinador = User.objects.create_user(username='coordinador', password='clave-segura')
        perfil = Perfil.objects.get(usuario=coordinador)
        perfil.rol = Rol.objects.get(codigo='coordinador')
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.client.force_login(coordinador)

        respuesta = self.client.post(
            reverse('evidencias:validar', args=[evidencia.pk]),
            {'accion': 'aprobar', 'comentario': ''},
        )

        evidencia.refresh_from_db()
        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(evidencia.estado, Evidencia.Estado.PENDIENTE)

    def test_archivo_no_se_expone_por_su_ruta_fisica_de_media(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/privada.png',
            subido_por=self.creador,
        )

        respuesta = self.client.get(f'/media/{evidencia.archivo.name}')

        self.assertEqual(respuesta.status_code, 404)

    def test_detalle_muestra_todas_las_evidencias_del_creador(self):
        for nombre in ('uno.png', 'dos.mp4'):
            Evidencia.objects.create(
                atencion=self.atencion,
                archivo=f'evidencias/{nombre}',
                subido_por=self.creador,
            )

        respuesta = self.client.get(reverse('atenciones:detalle', args=[self.atencion.pk]))

        prefijo = f'{timezone.localtime().strftime("%Y%m%d")}_vicentetest_'
        self.assertContains(respuesta, f'{prefijo}imagen_')
        self.assertContains(respuesta, f'{prefijo}video_')
        self.assertContains(respuesta, '<video', html=False)
        self.assertContains(respuesta, '<img', html=False)
        self.assertEqual(respuesta.context['evidencias'].count(), 2)

    def test_estado_del_listado_usa_paneles_de_color_por_prioridad(self):
        lista = reverse('atenciones:lista')
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Sin evidencia')
        self.assertContains(respuesta, 'bg-light text-secondary border')

        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/aprobada.png',
            subido_por=self.creador,
            estado=Evidencia.Estado.APROBADA,
        )
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Aprobada')
        self.assertContains(respuesta, 'bg-success text-white')

        evidencia_pendiente = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Pendiente')
        self.assertContains(respuesta, 'bg-secondary text-white')

        evidencia_pendiente.estado = Evidencia.Estado.RECHAZADA
        evidencia_pendiente.save(update_fields=['estado'])
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Rechazada')
        self.assertContains(respuesta, 'bg-danger text-white')

    def test_propietario_puede_ver_archivo_y_mime_de_servido_es_seguro(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {'archivos': [imagen_valida()]},
        )
        self.assertEqual(respuesta.status_code, 302)
        evidencia = Evidencia.objects.get()

        archivo = self.client.get(reverse('evidencia_archivo', args=[evidencia.pk]))

        self.assertEqual(archivo.status_code, 200)
        self.assertEqual(archivo['Content-Type'], 'image/png')
        self.assertEqual(archivo['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', archivo['Cache-Control'])


class AtencionVaAlTuboTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(nombre='Tubo Norte')
        self.delegacion_b = Delegacion.objects.create(nombre='Tubo Centro')
        self.tipo = TipoAtencion.objects.create(codigo='TUBO-T', nombre='Tipo tubo')
        self.subatencion = SubAtencion.objects.create(
            codigo='TUBO-S',
            nombre='Subtipo tubo',
            tipo=self.tipo,
        )
        self.roles = {}
        self.users = {}
        for codigo in (
            'funcionario',
            'verificador',
            'coordinador',
            'delegado',
        ):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol
            self.users[codigo] = self.crear_usuario(
                f'tubo-{codigo}',
                rol,
                self.delegacion_a,
            )
        self.admin = User.objects.create_superuser(
            username='tubo-admin',
            email='tubo-admin@example.com',
            password='clave-segura',
        )
        self.actividad = self.crear_actividad(
            'Actividad base',
            creador=self.users['funcionario'],
        )

    def crear_usuario(self, username, rol, delegacion, delegaciones=None):
        user = User.objects.create_user(
            username=username,
            first_name='Nombre',
            last_name=username,
            password='clave-segura',
        )
        perfil = Perfil.objects.get(usuario=user)
        if rol:
            perfil.rol = rol
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set(delegaciones or [delegacion])
        return user

    def crear_actividad(
        self,
        titulo,
        *,
        creador=None,
        delegacion=None,
        va_al_tubo=False,
        activo=True,
        estado=AtencionCiudadana.Estado.REGISTRADA,
    ):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            estado=estado,
            activo=activo,
            solicitante=titulo,
            tipo=self.tipo,
            subatencion=self.subatencion,
            va_al_tubo=va_al_tubo,
            descripcion=titulo,
            delegacion=delegacion or self.delegacion_a,
            responsable=creador or self.users['funcionario'],
            creado_por=creador,
        )

    def login(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = (delegacion or self.delegacion_a).pk
        session.save()

    def cambiar(self, user, actividad, valor, delegacion=None, **extra):
        self.login(user, delegacion)
        return self.client.post(
            reverse('atenciones:cambiar_va_al_tubo', args=[actividad.pk]),
            {'va_al_tubo': 'true' if valor else 'false', **extra},
        )

    def test_todos_los_roles_autorizados_definen_valor_al_crear(self):
        creadores = {
            **self.users,
            'administrador': self.admin,
        }
        for rol, user in creadores.items():
            with self.subTest(rol=rol):
                self.login(user)
                response = self.client.post(
                    reverse('atenciones:crear'),
                    {
                        'titulo': f'Creada por {rol}',
                        'fecha': '2026-10-25',
                        'solicitante': f'Solicitante {rol}',
                        'tipo': self.tipo.pk,
                        'subatencion': self.subatencion.pk,
                        'va_al_tubo': 'on',
                        'descripcion': 'Actividad de prueba',
                    },
                )
                self.assertEqual(response.status_code, 302)
                creada = AtencionCiudadana.objects.get(titulo=f'Creada por {rol}')
                self.assertTrue(creada.va_al_tubo)
                self.assertEqual(creada.creado_por, user)
                self.assertEqual(creada.delegacion, self.delegacion_a)

    def test_funcionario_y_verificador_modifican_solo_actividad_propia(self):
        propia_funcionario = self.crear_actividad(
            'Propia funcionario',
            creador=self.users['funcionario'],
        )
        propia_verificador = self.crear_actividad(
            'Propia verificador',
            creador=self.users['verificador'],
        )
        ajena = self.crear_actividad(
            'Actividad ajena',
            creador=self.users['coordinador'],
        )
        for rol, propia in (
            ('funcionario', propia_funcionario),
            ('verificador', propia_verificador),
        ):
            with self.subTest(rol=rol):
                response = self.cambiar(self.users[rol], propia, True)
                self.assertEqual(response.status_code, 302)
                propia.refresh_from_db()
                self.assertTrue(propia.va_al_tubo)
                response = self.cambiar(self.users[rol], ajena, True)
                self.assertEqual(response.status_code, 404)
                ajena.refresh_from_db()
                self.assertFalse(ajena.va_al_tubo)

    def test_coordinador_y_delegado_cambian_en_su_delegacion_no_en_otra(self):
        en_otra = self.crear_actividad(
            'Actividad otra delegación',
            delegacion=self.delegacion_b,
            creador=self.users['funcionario'],
        )
        for rol in ('coordinador', 'delegado'):
            with self.subTest(rol=rol):
                response = self.cambiar(self.users[rol], self.actividad, True)
                self.assertEqual(response.status_code, 302)
                self.actividad.refresh_from_db()
                self.assertTrue(self.actividad.va_al_tubo)
                response = self.cambiar(self.users[rol], en_otra, True)
                self.assertEqual(response.status_code, 404)
                en_otra.refresh_from_db()
                self.assertFalse(en_otra.va_al_tubo)

    def test_administrador_modifica_globalmente(self):
        en_otra = self.crear_actividad(
            'Global',
            delegacion=self.delegacion_b,
        )

        response = self.cambiar(
            self.admin,
            en_otra,
            True,
            delegacion=self.delegacion_a,
        )
        self.assertEqual(response.status_code, 404)
        self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        response = self.client.post(reverse('atenciones:cambiar_va_al_tubo', args=[en_otra.pk]),
                                    {'va_al_tubo': 'true'})
        self.assertEqual(response.status_code, 302)
        en_otra.refresh_from_db()
        self.assertTrue(en_otra.va_al_tubo)

    def test_usuario_transferido_no_cambia_actividad_historica_fuera_de_su_alcance(self):
        perfil = self.users['funcionario'].perfil
        perfil.delegacion = self.delegacion_b
        perfil.save(update_fields=['delegacion'])
        perfil.delegaciones.set([self.delegacion_b])
        self.login(self.users['funcionario'], self.delegacion_a)

        response = self.client.post(
            reverse('atenciones:cambiar_va_al_tubo', args=[self.actividad.pk]),
            {'va_al_tubo': 'true'},
        )

        self.assertEqual(response.status_code, 404)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.delegacion, self.delegacion_a)
        self.assertFalse(self.actividad.va_al_tubo)

    def test_inactiva_y_cerrada_rechazan_y_reabierta_permite(self):
        deshabilitada = self.crear_actividad(
            'Deshabilitada',
            activo=False,
        )
        cerrada = self.crear_actividad(
            'Cerrada',
            estado=AtencionCiudadana.Estado.CERRADA,
        )
        for rol, user in {'administrador': self.admin, **self.users}.items():
            with self.subTest(rol=rol):
                self.assertEqual(self.cambiar(user, deshabilitada, True).status_code, 404)
                self.assertEqual(self.cambiar(user, cerrada, True).status_code, 404)
        self.login(self.users['coordinador'])
        response = self.client.post(
            reverse('atenciones:cambiar_estado', args=[cerrada.pk]),
            {'estado': AtencionCiudadana.Estado.EN_PROCESO},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.cambiar(self.users['coordinador'], cerrada, True).status_code, 302)
        cerrada.refresh_from_db()
        self.assertEqual(cerrada.estado, AtencionCiudadana.Estado.EN_PROCESO)
        self.assertTrue(cerrada.va_al_tubo)

    def test_post_solo_cambia_va_al_tubo_y_audita_anterior_nuevo(self):
        actividad = self.crear_actividad(
            'Inmutable',
            creador=self.users['funcionario'],
        )

        response = self.cambiar(
            self.users['funcionario'],
            actividad,
            True,
            delegacion=self.delegacion_b,
            estado=AtencionCiudadana.Estado.CERRADA,
            activo='false',
            creado_por=self.users['verificador'].pk,
            tipo=self.tipo.pk + 1,
            subatencion=self.subatencion.pk + 1,
        )

        self.assertEqual(response.status_code, 302)
        actividad.refresh_from_db()
        self.assertTrue(actividad.va_al_tubo)
        self.assertEqual(actividad.delegacion, self.delegacion_a)
        self.assertEqual(actividad.creado_por, self.users['funcionario'])
        self.assertEqual(actividad.estado, AtencionCiudadana.Estado.REGISTRADA)
        self.assertTrue(actividad.activo)
        self.assertEqual(actividad.tipo, self.tipo)
        self.assertEqual(actividad.subatencion, self.subatencion)
        auditoria = RegistroAuditoria.objects.get(
            accion='cambiar_va_al_tubo',
            objeto_id=str(actividad.pk),
        )
        self.assertEqual(auditoria.usuario, self.users['funcionario'])
        self.assertIn('No → Sí', auditoria.descripcion)
        self.assertIsNotNone(auditoria.timestamp)

    def test_mismo_valor_no_genera_auditoria_y_get_no_modifica(self):
        actividad = self.crear_actividad(
            'Sin cambio',
            va_al_tubo=True,
            creador=self.users['funcionario'],
        )
        self.login(self.users['funcionario'])
        url = reverse('atenciones:cambiar_va_al_tubo', args=[actividad.pk])

        get_response = self.client.get(url)
        post_response = self.client.post(url, {'va_al_tubo': 'true'})

        self.assertEqual(get_response.status_code, 405)
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(
            RegistroAuditoria.objects.filter(
                accion='cambiar_va_al_tubo',
                objeto_id=str(actividad.pk),
            ).exists()
        )

    def test_lista_detalle_y_filtros_muestran_valor_sin_ampliar_alcance(self):
        si_local = self.crear_actividad(
            'Sí local',
            va_al_tubo=True,
            creador=self.users['funcionario'],
        )
        no_local = self.crear_actividad(
            'No local',
            creador=self.users['funcionario'],
        )
        otra = self.crear_actividad(
            'Sí otra',
            delegacion=self.delegacion_b,
            va_al_tubo=True,
            creador=self.users['funcionario'],
        )
        self.login(self.users['coordinador'])

        lista = self.client.get(reverse('atenciones:lista'))
        self.assertContains(lista, 'Actividad')
        self.assertContains(lista, 'Tipo / Subatención')
        self.assertContains(lista, 'Creada por:')
        self.assertContains(lista, 'Va al tubo')
        self.assertContains(lista, 'No va al tubo')
        si = self.client.get(
            reverse('atenciones:lista'),
            {'va_al_tubo': 'true'},
        )
        no = self.client.get(
            reverse('atenciones:lista'),
            {'va_al_tubo': 'false'},
        )
        si_ids = {item.pk for item in si.context['atenciones']}
        no_ids = {item.pk for item in no.context['atenciones']}
        self.assertEqual(si_ids, {si_local.pk})
        self.assertEqual(no_ids, {self.actividad.pk, no_local.pk})
        self.assertNotIn(otra.pk, si_ids | no_ids)
        self.assertContains(
            self.client.get(reverse('atenciones:detalle', args=[si_local.pk])),
            'Va al tubo:',
        )
        self.assertContains(
            self.client.get(reverse('atenciones:detalle', args=[no_local.pk])),
            'No',
        )

    def test_listado_agrupa_datos_y_acciones_en_dropdown_post_seguro(self):
        actividad = self.crear_actividad(
            'Actividad migrada visual',
            creador=self.users['funcionario'],
            va_al_tubo=False,
        )
        self.login(self.users['funcionario'])

        response = self.client.get(reverse('atenciones:lista'))

        self.assertEqual(response.status_code, 200)
        for columna in (
            'Fecha',
            'Actividad',
            'Solicitante',
            'Tipo / Subatención',
            'Delegación',
            'Responsable',
            'Estado',
            'Evidencia',
            'Acciones',
        ):
            with self.subTest(columna=columna):
                self.assertContains(response, f'<th>{columna}</th>', html=True)

        self.assertContains(response, 'Actividad migrada visual')
        self.assertContains(response, 'Creada por: Nombre tubo-funcionario')
        self.assertContains(response, 'No va al tubo')
        self.assertContains(response, self.tipo.nombre)
        self.assertContains(response, self.subatencion.nombre)
        self.assertContains(response, self.delegacion_a.nombre)
        self.assertContains(response, 'Registrada')
        self.assertContains(response, 'Sin evidencia')
        self.assertContains(response, 'dropdown-toggle')
        self.assertContains(response, 'Acciones')
        self.assertContains(response, 'Ver')
        self.assertContains(
            response,
            reverse('atenciones:detalle', args=[actividad.pk]),
        )
        self.assertContains(response, 'Marcar Va al tubo')
        self.assertNotContains(response, 'Marcar No va al tubo')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertNotContains(response, 'Deshabilitar')
        self.assertNotContains(response, 'Habilitar')
        self.assertContains(response, 'table-responsive')

        actividad.va_al_tubo = True
        actividad.save(update_fields=['va_al_tubo'])
        response_actualizada = self.client.get(
            reverse('atenciones:lista'),
            {'va_al_tubo': 'true'},
        )
        self.assertContains(response_actualizada, 'Va al tubo')
        self.assertContains(response_actualizada, 'Marcar No va al tubo')
        self.assertNotContains(response_actualizada, 'Marcar Va al tubo')

    def test_listado_muestra_historicas_y_badges_estado_evidencia(self):
        inactiva = self.crear_actividad(
            'Actividad deshabilitada visible',
            activo=False,
        )
        evidencia = Evidencia.objects.create(
            atencion=inactiva,
            archivo='evidencias/estado-pendiente.png',
            subido_por=self.users['funcionario'],
        )
        self.login(self.users['coordinador'])

        response = self.client.get(reverse('atenciones:lista'))

        self.assertContains(response, 'Actividad deshabilitada visible')
        self.assertContains(response, 'Deshabilitada')
        self.assertContains(response, 'Pendiente')
        self.assertContains(response, 'badge bg-secondary text-white')

    def test_evidencias_y_compromisos_permanecen_intactos(self):
        actividad = self.crear_actividad(
            'Con relaciones',
            creador=self.users['funcionario'],
        )
        evidencia = Evidencia.objects.create(
            atencion=actividad,
            archivo='evidencias/tubo.png',
            subido_por=self.users['funcionario'],
        )
        compromiso = Compromiso.objects.create(
            titulo='Compromiso tubo',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.users['funcionario'],
            delegacion=self.delegacion_a,
        )
        compromiso.actividades.add(actividad)

        response = self.cambiar(self.users['funcionario'], actividad, True)

        self.assertEqual(response.status_code, 302)
        actividad.refresh_from_db()
        evidencia.refresh_from_db()
        compromiso.refresh_from_db()
        self.assertTrue(actividad.va_al_tubo)
        self.assertEqual(evidencia.atencion, actividad)
        self.assertTrue(compromiso.actividades.filter(pk=actividad.pk).exists())

    def test_admin_no_edita_va_al_tubo_en_actividad_existente(self):
        model_admin = AtencionCiudadanaAdmin(AtencionCiudadana, admin.site)
        request = type('Request', (), {'user': self.admin})()

        self.assertIn('va_al_tubo', model_admin.get_readonly_fields(request, self.actividad))
        self.assertNotIn('va_al_tubo', model_admin.get_readonly_fields(request))
