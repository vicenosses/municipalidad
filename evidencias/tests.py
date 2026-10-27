from io import BytesIO
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from PIL import Image

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.forms import EvidenciaForm
from evidencias.models import Evidencia
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


def crear_imagen(formato='PNG'):
    salida = BytesIO()
    Image.new('RGB', (2, 2), color='red').save(salida, format=formato)
    return salida.getvalue()


class EvidenciaFormTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.rol.activo = True
        self.rol.save(update_fields=['activo'])
        self.usuario = User.objects.create_user(username='funcionario', password='clave-segura')
        self.perfil = Perfil.objects.get(usuario=self.usuario)
        self.perfil.rol = self.rol
        self.perfil.delegacion = self.delegacion
        self.perfil.save()
        self.perfil.delegaciones.add(self.delegacion)
        self.usuario.perfil = self.perfil
        self.tipo = TipoAtencion.objects.create(codigo='TIP-1', nombre='Tipo')
        self.subatencion = SubAtencion.objects.create(
            codigo='SUB-1',
            nombre='Subatención',
            tipo=self.tipo,
        )
        self.actividad = AtencionCiudadana.objects.create(
            titulo='Actividad',
            fecha='2026-10-17',
            solicitante='Solicitante',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Descripción',
            responsable=self.usuario,
            delegacion=self.delegacion,
        )

    def formulario(self, actividad=None, archivo=None):
        request = RequestFactory().post('/')
        request.user = self.usuario
        request.session = {'delegacion_activa_id': self.delegacion.pk}
        return EvidenciaForm(
            data={'atencion': actividad.pk if actividad else ''},
            files={'archivo': archivo} if archivo else {},
            request=request,
        )

    def test_acepta_imagen_png_real_asociada_a_actividad(self):
        archivo = SimpleUploadedFile('foto.png', crear_imagen(), content_type='image/png')
        form = self.formulario(self.actividad, archivo)

        self.assertIn(self.actividad, form.fields['atencion'].queryset)
        self.assertTrue(form.is_valid(), form.errors)
        evidencia = form.save(commit=False)
        evidencia.subido_por = self.usuario
        evidencia.save()
        self.assertEqual(evidencia.atencion, self.actividad)
        self.assertIsNone(evidencia.compromiso_id)

    def test_rechaza_contenido_que_no_es_jpg_ni_png(self):
        archivo = SimpleUploadedFile(
            'foto.gif',
            crear_imagen('GIF'),
            content_type='image/png',
        )
        form = self.formulario(self.actividad, archivo)

        self.assertFalse(form.is_valid())
        self.assertIn('archivo', form.errors)

    def test_funcionario_no_puede_asociar_actividad_de_otro_responsable(self):
        otro_usuario = User.objects.create_user(username='otro', password='clave-segura')
        otra_actividad = AtencionCiudadana.objects.create(
            titulo='Otra actividad',
            fecha='2026-10-17',
            solicitante='Otro solicitante',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Descripción',
            responsable=otro_usuario,
            delegacion=self.delegacion,
        )
        archivo = SimpleUploadedFile('foto.png', crear_imagen(), content_type='image/png')
        form = self.formulario(otra_actividad, archivo)

        self.assertFalse(form.is_valid())
        self.assertIn('atencion', form.errors)

    def test_verificador_no_puede_validar_evidencia_de_otra_delegacion(self):
        otra_delegacion = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        compromiso = Compromiso.objects.create(
            titulo='Compromiso ajeno',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.usuario,
            delegacion=otra_delegacion,
        )
        evidencia = Evidencia.objects.create(
            compromiso=compromiso,
            archivo='evidencias/prueba.png',
            subido_por=self.usuario,
        )
        rol_verificador, _ = Rol.objects.get_or_create(
            codigo='verificador',
            defaults={'nombre': 'Verificador'},
        )
        self.perfil.rol = rol_verificador
        self.perfil.save()
        self.client.force_login(self.usuario)
        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion.pk
        session.save()

        respuesta = self.client.get(reverse('evidencias:validar', args=[evidencia.pk]))

        self.assertEqual(respuesta.status_code, 404)

    def test_evidencia_admite_atencion_o_compromiso(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.usuario,
            delegacion=self.delegacion,
        )
        evidencia_actividad = Evidencia.objects.create(
            atencion=self.actividad,
            archivo='evidencias/actividad.png',
            subido_por=self.usuario,
        )
        evidencia_compromiso = Evidencia.objects.create(
            compromiso=compromiso,
            archivo='evidencias/compromiso.png',
            subido_por=self.usuario,
        )

        self.assertEqual(evidencia_actividad.atencion, self.actividad)
        self.assertIsNone(evidencia_actividad.compromiso_id)
        self.assertEqual(evidencia_compromiso.compromiso, compromiso)
        self.assertIsNone(evidencia_compromiso.atencion_id)

    def test_evidencia_no_admite_ambos_origenes_ni_quedar_sin_origen(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.usuario,
            delegacion=self.delegacion,
        )
        for evidencia in (
            Evidencia(
                atencion=self.actividad,
                compromiso=compromiso,
                archivo='evidencias/ambos.png',
                subido_por=self.usuario,
            ),
            Evidencia(archivo='evidencias/ninguno.png', subido_por=self.usuario),
        ):
            with self.subTest(atencion=evidencia.atencion_id, compromiso=evidencia.compromiso_id):
                with self.assertRaises(ValidationError):
                    evidencia.clean()

    def test_listado_y_detalle_muestran_actividad_principal(self):
        evidencia = Evidencia.objects.create(
            atencion=self.actividad,
            archivo='evidencias/actividad.png',
            subido_por=self.usuario,
        )
        self.client.force_login(self.usuario)

        listado = self.client.get(reverse('evidencias:lista'), {'origen': 'atencion'})
        detalle = self.client.get(reverse('evidencias:detalle', args=[evidencia.pk]))

        self.assertEqual(listado.status_code, 200)
        self.assertContains(listado, 'Actividad')
        self.assertContains(listado, self.actividad.titulo)
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, self.actividad.titulo)

    def test_descarga_no_permite_actividad_de_otro_usuario(self):
        otro_usuario = User.objects.create_user(username='otro', password='clave-segura')
        otra_actividad = AtencionCiudadana.objects.create(
            titulo='Actividad ajena',
            fecha='2026-10-18',
            solicitante='Otro solicitante',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Descripción',
            responsable=otro_usuario,
            delegacion=self.delegacion,
        )
        evidencia = Evidencia.objects.create(
            atencion=otra_actividad,
            archivo='evidencias/actividad-ajena.png',
            subido_por=otro_usuario,
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('evidencia_archivo', args=[evidencia.pk]))

        self.assertEqual(respuesta.status_code, 404)

    def test_filtro_por_origen_distingue_actividad_de_agenda(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.usuario,
            delegacion=self.delegacion,
        )
        agenda_evidencia = Evidencia.objects.create(
            compromiso=compromiso,
            archivo='evidencias/agenda.png',
            subido_por=self.usuario,
        )
        actividad_evidencia = Evidencia.objects.create(
            atencion=self.actividad,
            archivo='evidencias/actividad.png',
            subido_por=self.usuario,
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('evidencias:lista'), {'origen': 'agenda'})

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, agenda_evidencia.identificador)
        self.assertNotContains(respuesta, actividad_evidencia.identificador)
        detalle = self.client.get(reverse('evidencias:detalle', args=[agenda_evidencia.pk]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'Agenda')


class EvidenciaRoleAuthorizationTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix='evidencia-role-test-')
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        self.delegacion_a = Delegacion.objects.create(codigo='EVI-A', nombre='Evidencia A')
        self.delegacion_b = Delegacion.objects.create(codigo='EVI-B', nombre='Evidencia B')
        self.roles = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': f'Evidencia {codigo}'},
            )
            rol.activo = True
            rol.permisos = {}
            rol.save(update_fields=['activo', 'permisos'])
            self.roles[codigo] = rol

        self.users = {
            codigo: self.crear_usuario(codigo, codigo, self.delegacion_a)
            for codigo in self.roles
        }
        self.tipo = TipoAtencion.objects.create(codigo='EVI-T', nombre='Tipo evidencia')
        self.subatencion = SubAtencion.objects.create(
            codigo='EVI-S',
            nombre='Subatención evidencia',
            tipo=self.tipo,
        )
        self.actividad_a = self.crear_actividad(
            'Actividad A',
            self.delegacion_a,
            self.users['funcionario'],
        )
        self.actividad_b = self.crear_actividad(
            'Actividad B',
            self.delegacion_b,
            self.users['funcionario'],
        )
        self.compromiso_a = self.crear_compromiso(
            'Compromiso A',
            self.delegacion_a,
            self.users['funcionario'],
        )
        self.compromiso_b = self.crear_compromiso(
            'Compromiso B',
            self.delegacion_b,
            self.users['funcionario'],
        )

    def crear_usuario(self, username, codigo_rol, delegacion):
        user = User.objects.create_user(username=username, password='clave-segura')
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = self.roles[codigo_rol]
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set([delegacion])
        user.perfil = perfil
        return user

    def crear_actividad(self, titulo, delegacion, responsable, creado_por=None):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            solicitante=titulo,
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion=titulo,
            delegacion=delegacion,
            responsable=responsable,
            creado_por=creado_por,
        )

    def crear_compromiso(self, titulo, delegacion, responsable, creado_por=None):
        return Compromiso.objects.create(
            titulo=titulo,
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=responsable,
            delegacion=delegacion,
            creado_por=creado_por,
        )

    def activar_delegacion(self, user, delegacion):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = delegacion.pk
        session.save()

    def subir_archivo(self):
        return SimpleUploadedFile('foto.png', crear_imagen(), content_type='image/png')

    def crear_evidencia(self, *, atencion=None, compromiso=None):
        return Evidencia.objects.create(
            atencion=atencion,
            compromiso=compromiso,
            archivo='evidencias/prueba.png',
            subido_por=self.users['funcionario'],
        )

    def subir_generica(self, user, *, atencion=None, compromiso=None):
        self.activar_delegacion(user, self.delegacion_a)
        if user == self.users['administrador']:
            self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        return self.client.post(
            reverse('evidencias:crear'),
            {
                'atencion': atencion.pk if atencion else '',
                'compromiso': compromiso.pk if compromiso else '',
                'descripcion': 'Carga genérica',
                'archivo': self.subir_archivo(),
            },
        )

    def validar(self, user, evidencia, accion='aprobar'):
        self.activar_delegacion(user, self.delegacion_a)
        return self.client.post(
            reverse('evidencias:validar', args=[evidencia.pk]),
            {'accion': accion, 'comentario': ''},
        )

    def test_funcionario_y_verificador_solo_suben_a_sus_actividades(self):
        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                user = self.users[rol]
                actividad_propia = self.crear_actividad(
                    f'Actividad propia {rol}',
                    self.delegacion_a,
                    user,
                )
                self.activar_delegacion(user, self.delegacion_a)

                propia = self.client.post(
                    reverse('evidencias:atencion_crear', args=[actividad_propia.pk]),
                    {'archivos': [self.subir_archivo()]},
                )
                ajena = self.client.post(
                    reverse('evidencias:atencion_crear', args=[self.actividad_b.pk]),
                    {'archivos': [self.subir_archivo()]},
                )

                self.assertEqual(propia.status_code, 302)
                self.assertEqual(ajena.status_code, 404)
                self.assertTrue(Evidencia.objects.filter(atencion=actividad_propia, subido_por=user).exists())
                self.assertFalse(Evidencia.objects.filter(atencion=self.actividad_b, subido_por=user).exists())

    def test_funcionario_y_verificador_solo_suben_a_compromisos_mientras_responsables(self):
        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                user = self.users[rol]
                compromiso = self.crear_compromiso(
                    f'Compromiso {rol}',
                    self.delegacion_a,
                    user,
                )
                self.activar_delegacion(user, self.delegacion_a)
                propia = self.client.post(
                    reverse('evidencias:agenda_crear', args=[compromiso.pk]),
                    {'archivos': [self.subir_archivo()]},
                )
                self.assertEqual(propia.status_code, 302)
                self.assertTrue(Evidencia.objects.filter(compromiso=compromiso, subido_por=user).exists())

                compromiso.responsable = self.users['coordinador']
                compromiso.save(update_fields=['responsable'])
                revocada = self.client.post(
                    reverse('evidencias:agenda_crear', args=[compromiso.pk]),
                    {'archivos': [self.subir_archivo()]},
                )
                self.assertEqual(revocada.status_code, 404)
                self.assertEqual(Evidencia.objects.filter(compromiso=compromiso).count(), 1)

    def test_carga_generica_bloquea_actividad_cerrada_deshabilitada_y_ajena(self):
        for field, estado, activo in (
            ('cerrada', AtencionCiudadana.Estado.CERRADA, True),
            ('deshabilitada', AtencionCiudadana.Estado.REGISTRADA, False),
        ):
            with self.subTest(caso=field):
                actividad = self.actividad_a
                actividad.estado = estado
                actividad.activo = activo
                actividad.responsable = self.users['funcionario']
                actividad.save(update_fields=['estado', 'activo', 'responsable'])
                respuesta = self.subir_generica(
                    self.users['funcionario'],
                    atencion=actividad,
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(Evidencia.objects.filter(atencion=actividad).exists())
                actividad.estado = AtencionCiudadana.Estado.REGISTRADA
                actividad.activo = True
                actividad.save(update_fields=['estado', 'activo'])

        for rol in ('funcionario', 'verificador'):
            with self.subTest(rol=rol):
                respuesta = self.subir_generica(
                    self.users[rol],
                    atencion=self.actividad_b,
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(Evidencia.objects.filter(atencion=self.actividad_b).exists())

    def test_carga_generica_respeta_responsable_y_reasignacion_de_compromiso(self):
        compromiso = self.crear_compromiso(
            'Compromiso reasignado',
            self.delegacion_a,
            self.users['funcionario'],
        )
        permitida = self.subir_generica(self.users['funcionario'], compromiso=compromiso)
        self.assertEqual(permitida.status_code, 302)

        compromiso.responsable = self.users['coordinador']
        compromiso.save(update_fields=['responsable'])
        revocada = self.subir_generica(self.users['funcionario'], compromiso=compromiso)
        self.assertEqual(revocada.status_code, 200)
        self.assertEqual(Evidencia.objects.filter(compromiso=compromiso).count(), 1)

    def test_carga_generica_respeta_coordinador_delegado_y_administrador(self):
        coordinador = self.subir_generica(
            self.users['coordinador'],
            compromiso=self.compromiso_a,
        )
        self.assertEqual(coordinador.status_code, 200)
        self.assertFalse(Evidencia.objects.filter(compromiso=self.compromiso_a).exists())

        delegado = self.subir_generica(
            self.users['delegado'],
            atencion=self.actividad_a,
        )
        self.assertEqual(delegado.status_code, 302)
        delegado_ajeno = self.subir_generica(
            self.users['delegado'],
            atencion=self.actividad_b,
        )
        self.assertEqual(delegado_ajeno.status_code, 200)
        self.assertFalse(Evidencia.objects.filter(atencion=self.actividad_b).exists())

        administrador = self.subir_generica(
            self.users['administrador'],
            atencion=self.actividad_b,
        )
        self.assertEqual(administrador.status_code, 302)
        self.assertTrue(Evidencia.objects.filter(atencion=self.actividad_b).exists())

    def test_coordinador_solo_puede_subir_a_registros_de_los_que_es_responsable(self):
        compromiso = self.crear_compromiso(
            'Compromiso coordinador',
            self.delegacion_a,
            self.users['funcionario'],
        )
        self.activar_delegacion(self.users['coordinador'], self.delegacion_a)

        respuesta = self.client.post(
            reverse('evidencias:agenda_crear', args=[compromiso.pk]),
            {'archivos': [self.subir_archivo()]},
        )

        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(Evidencia.objects.filter(compromiso=compromiso).exists())

    def test_delegado_puede_agregar_evidencia_a_registros_de_su_delegacion(self):
        self.activar_delegacion(self.users['delegado'], self.delegacion_a)

        respuesta_actividad = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.actividad_a.pk]),
            {'archivos': [self.subir_archivo()]},
        )
        respuesta_compromiso = self.client.post(
            reverse('evidencias:agenda_crear', args=[self.compromiso_a.pk]),
            {'archivos': [self.subir_archivo()]},
        )
        respuesta_ajena = self.client.post(
            reverse('evidencias:agenda_crear', args=[self.compromiso_b.pk]),
            {'archivos': [self.subir_archivo()]},
        )

        self.assertEqual(respuesta_actividad.status_code, 302)
        self.assertEqual(respuesta_compromiso.status_code, 302)
        self.assertEqual(respuesta_ajena.status_code, 404)

    def test_funcionario_y_coordinador_no_pueden_validar(self):
        evidencia = self.crear_evidencia(compromiso=self.compromiso_a)
        for rol in ('funcionario', 'coordinador'):
            with self.subTest(rol=rol):
                self.client.force_login(self.users[rol])
                respuesta = self.client.post(
                    reverse('evidencias:validar', args=[evidencia.pk]),
                    {'accion': 'aprobar', 'comentario': ''},
                )
                self.assertEqual(respuesta.status_code, 403)
                evidencia.refresh_from_db()
                self.assertEqual(evidencia.estado, Evidencia.Estado.PENDIENTE)

    def test_verificador_y_delegado_validan_ambos_origenes_solo_en_su_delegacion(self):
        for rol in ('verificador', 'delegado'):
            with self.subTest(rol=rol):
                actividad = self.crear_evidencia(atencion=self.actividad_a)
                compromiso = self.crear_evidencia(compromiso=self.compromiso_a)
                ajena = self.crear_evidencia(compromiso=self.compromiso_b)

                for evidencia in (actividad, compromiso):
                    respuesta = self.validar(self.users[rol], evidencia)
                    self.assertEqual(respuesta.status_code, 302)
                    evidencia.refresh_from_db()
                    self.assertEqual(evidencia.estado, Evidencia.Estado.APROBADA)

                respuesta_ajena = self.validar(self.users[rol], ajena)
                self.assertEqual(respuesta_ajena.status_code, 404)
                ajena.refresh_from_db()
                self.assertEqual(ajena.estado, Evidencia.Estado.PENDIENTE)

    def test_verificador_no_valida_evidencia_de_registro_que_creo(self):
        verificador = self.users['verificador']
        actividad = self.crear_actividad(
            'Actividad creada por verificador',
            self.delegacion_a,
            self.users['funcionario'],
            creado_por=verificador,
        )
        compromiso = self.crear_compromiso(
            'Compromiso creado por verificador',
            self.delegacion_a,
            self.users['funcionario'],
            creado_por=verificador,
        )
        compromiso.responsable = self.users['coordinador']
        compromiso.save(update_fields=['responsable'])
        evidencias = (
            self.crear_evidencia(atencion=actividad),
            self.crear_evidencia(compromiso=compromiso),
        )

        self.activar_delegacion(verificador, self.delegacion_a)
        listado = self.client.get(reverse('evidencias:lista'))
        self.assertEqual(listado.status_code, 200)
        for evidencia in evidencias:
            with self.subTest(origen=evidencia.origen):
                detalle = self.client.get(
                    reverse('evidencias:detalle', args=[evidencia.pk])
                )
                self.assertEqual(detalle.status_code, 200)
                self.assertNotContains(
                    detalle,
                    reverse('evidencias:validar', args=[evidencia.pk]),
                )
                respuesta = self.client.post(
                    reverse('evidencias:validar', args=[evidencia.pk]),
                    {'accion': 'aprobar', 'comentario': ''},
                )
                self.assertEqual(respuesta.status_code, 404)
                evidencia.refresh_from_db()
                self.assertEqual(evidencia.estado, Evidencia.Estado.PENDIENTE)
        for evidencia in evidencias:
            self.assertNotContains(
                listado,
                reverse('evidencias:validar', args=[evidencia.pk]),
            )

    def test_verificador_puede_validar_registros_creados_por_otra_persona(self):
        creador = self.users['delegado']
        actividad = self.crear_actividad(
            'Actividad creada por delegado',
            self.delegacion_a,
            self.users['funcionario'],
            creado_por=creador,
        )
        compromiso = self.crear_compromiso(
            'Compromiso creado por delegado',
            self.delegacion_a,
            self.users['funcionario'],
            creado_por=creador,
        )
        evidencias = (
            self.crear_evidencia(atencion=actividad),
            self.crear_evidencia(compromiso=compromiso),
        )

        for evidencia in evidencias:
            with self.subTest(origen=evidencia.origen):
                respuesta = self.validar(self.users['verificador'], evidencia)
                self.assertEqual(respuesta.status_code, 302)
                evidencia.refresh_from_db()
                self.assertEqual(evidencia.estado, Evidencia.Estado.APROBADA)

    def test_creador_desconocido_no_se_interpreta_como_autovalidacion(self):
        actividad = self.crear_actividad(
            'Actividad histórica sin creador',
            self.delegacion_a,
            self.users['funcionario'],
        )
        compromiso = self.crear_compromiso(
            'Compromiso histórico sin creador',
            self.delegacion_a,
            self.users['funcionario'],
        )
        evidencias = (
            self.crear_evidencia(atencion=actividad),
            self.crear_evidencia(compromiso=compromiso),
        )
        self.assertIsNone(actividad.creado_por_id)
        self.assertIsNone(compromiso.creado_por_id)

        for evidencia in evidencias:
            with self.subTest(origen=evidencia.origen):
                respuesta = self.validar(self.users['verificador'], evidencia)
                self.assertEqual(respuesta.status_code, 302)
                evidencia.refresh_from_db()
                self.assertEqual(evidencia.estado, Evidencia.Estado.APROBADA)

    def test_administrador_normal_valida_actividad_y_compromiso_de_otra_delegacion(self):
        administrador = self.users['administrador']
        evidencia_actividad = self.crear_evidencia(atencion=self.actividad_b)
        evidencia_compromiso = self.crear_evidencia(compromiso=self.compromiso_b)
        self.client.force_login(administrador)

        for evidencia in (evidencia_actividad, evidencia_compromiso):
            respuesta = self.client.post(
                reverse('evidencias:validar', args=[evidencia.pk]),
                {'accion': 'aprobar', 'comentario': ''},
            )
            self.assertEqual(respuesta.status_code, 302)
            evidencia.refresh_from_db()
            self.assertEqual(evidencia.estado, Evidencia.Estado.APROBADA)

    def test_post_manipulado_no_permite_validar_fuera_de_alcance(self):
        evidencia = self.crear_evidencia(atencion=self.actividad_b)
        for rol in ('verificador', 'delegado'):
            with self.subTest(rol=rol):
                respuesta = self.validar(self.users[rol], evidencia, accion='rechazar')
                self.assertEqual(respuesta.status_code, 404)
                evidencia.refresh_from_db()
                self.assertEqual(evidencia.estado, Evidencia.Estado.PENDIENTE)
