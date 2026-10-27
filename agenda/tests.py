from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from agenda.forms import CompromisoForm
from agenda.models import Compromiso, HistorialCompromiso
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.models import Evidencia
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


class CompromisoFormTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.responsable = User.objects.create_user(username='responsable', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.responsable)
        perfil.rol = self.rol
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.otro = User.objects.create_user(username='externo', password='clave-segura')
        self.tipo = TipoAtencion.objects.create(codigo='TIP-FORM', nombre='Tipo formulario')
        self.subatencion = SubAtencion.objects.create(
            codigo='SUB-FORM',
            nombre='Subatención formulario',
            tipo=self.tipo,
        )

    def test_responsable_debe_pertenecer_a_la_delegacion(self):
        form = CompromisoForm(
            data={'responsable': self.responsable.pk},
            delegacion=self.delegacion,
        )
        self.assertIn(self.responsable, form.fields['responsable'].queryset)
        self.assertNotIn(self.otro, form.fields['responsable'].queryset)

    def test_no_permite_saltar_transiciones_de_estado(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso de prueba',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        self.assertIsNone(compromiso.creado_por)
        form = CompromisoForm(
            data={
                'titulo': compromiso.titulo,
                'descripcion': '',
                'solicitante': '',
                'area_apoyo': '',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': self.responsable.pk,
                'estado': Compromiso.Estado.REALIZADO,
                'observaciones': '',
                'actividades': [],
            },
            instance=compromiso,
            user=self.responsable,
            delegaciones=[self.delegacion],
        )
        self.assertFalse(form.is_valid(), form.cleaned_data)
        self.assertIn('estado', form.errors)

    def test_actividades_del_formulario_se_limita_a_las_delegaciones_indicadas(self):
        actividad_permitida = self.crear_actividad('Actividad permitida', self.delegacion)
        otra_delegacion = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        actividad_ajena = self.crear_actividad('Actividad ajena', otra_delegacion)
        actividad_deshabilitada = self.crear_actividad('Actividad inactiva', self.delegacion)
        actividad_deshabilitada.activo = False
        actividad_deshabilitada.save(update_fields=['activo'])

        form = CompromisoForm(delegaciones=[self.delegacion])

        self.assertIn(actividad_permitida, form.fields['actividades'].queryset)
        self.assertNotIn(actividad_ajena, form.fields['actividades'].queryset)
        self.assertNotIn(actividad_deshabilitada, form.fields['actividades'].queryset)

    def test_post_no_puede_asociar_actividad_deshabilitada(self):
        actividad = self.crear_actividad('Actividad deshabilitada', self.delegacion)
        actividad.activo = False
        actividad.save(update_fields=['activo'])

        form = CompromisoForm(
            data={'responsable': self.responsable.pk, 'actividades': [actividad.pk]},
            delegacion=self.delegacion,
            es_creacion=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('actividades', form.errors)

    def crear_actividad(self, titulo, delegacion):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-24',
            estado=AtencionCiudadana.Estado.REGISTRADA,
            solicitante='Solicitante',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion='Descripción de actividad',
            delegacion=delegacion,
            responsable=self.responsable,
        )


class AgendaWorkflowTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-COORD', nombre='Centro')
        self.rol_coordinador, _ = Rol.objects.get_or_create(
            codigo='coordinador',
            defaults={'nombre': 'Coordinador'},
        )
        self.coordinador = User.objects.create_user(username='coord', password='clave-segura')
        rol_funcionario, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.responsable = User.objects.create_user(username='func', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.responsable)
        perfil.rol = rol_funcionario
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        perfil = self.coordinador.perfil
        perfil.rol = self.rol_coordinador
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.assertEqual(perfil.rol_codigo, 'coordinador')
        self.tipo = TipoAtencion.objects.create(codigo='TIP-AGENDA', nombre='Tipo agenda')
        self.subatencion = SubAtencion.objects.create(
            codigo='SUB-AGENDA',
            nombre='Subatención agenda',
            tipo=self.tipo,
        )

    def crear_actividad(self, titulo, delegacion=None):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-24',
            estado=AtencionCiudadana.Estado.REGISTRADA,
            solicitante='Solicitante',
            tipo=self.tipo,
            subatencion=self.subatencion,
            descripcion=f'Descripción de {titulo}',
            delegacion=delegacion or self.delegacion,
            responsable=self.responsable,
        )

    def test_creacion_asocia_actividades_de_la_delegacion_activa(self):
        actividad = self.crear_actividad('Actividad para compromiso')
        otra_delegacion = Delegacion.objects.create(codigo='DEL-AGENDA-2', nombre='Norte')
        actividad_ajena = self.crear_actividad('Actividad de otra delegación', otra_delegacion)
        self.client.force_login(self.coordinador)
        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion.pk
        session.save()

        formulario = self.client.get(reverse('agenda:crear'))
        actividades_disponibles = formulario.context['form'].fields['actividades'].queryset
        self.assertIn(actividad, actividades_disponibles)
        self.assertNotIn(actividad_ajena, actividades_disponibles)

        respuesta = self.client.post(
            reverse('agenda:crear'),
            {
                'titulo': 'Compromiso asociado',
                'descripcion': '',
                'solicitante': '',
                'area_apoyo': '',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': self.responsable.pk,
                'observaciones': '',
                'actividades': [actividad.pk],
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        compromiso = Compromiso.objects.get(titulo='Compromiso asociado')
        self.assertEqual(compromiso.creado_por, self.coordinador)
        self.assertQuerySetEqual(compromiso.actividades.all(), [actividad])
        self.assertTrue(
            HistorialCompromiso.objects.filter(
                compromiso=compromiso,
                campo='creacion',
                realizado_por=self.coordinador,
            ).exists()
        )

    def test_edicion_actualiza_actividades_y_registra_historial(self):
        actividad_inicial = self.crear_actividad('Actividad inicial')
        actividad_nueva = self.crear_actividad('Actividad nueva')
        compromiso = Compromiso.objects.create(
            titulo='Compromiso editable',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
            creado_por=self.coordinador,
        )
        compromiso.actividades.add(actividad_inicial)
        self.client.force_login(self.coordinador)

        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            {
                'titulo': compromiso.titulo,
                'descripcion': '',
                'solicitante': '',
                'area_apoyo': '',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': self.responsable.pk,
                'estado': Compromiso.Estado.INGRESADO,
                'observaciones': '',
                'actividades': [actividad_nueva.pk],
                'motivo_cambio': '',
                'creado_por': self.responsable.pk,
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.creado_por, self.coordinador)
        self.assertQuerySetEqual(compromiso.actividades.all(), [actividad_nueva])
        cambio = HistorialCompromiso.objects.get(compromiso=compromiso, campo='actividades')
        self.assertEqual(cambio.valor_anterior, str(actividad_inicial.pk))
        self.assertEqual(cambio.valor_nuevo, str(actividad_nueva.pk))
        self.assertEqual(cambio.realizado_por, self.coordinador)

    def test_editar_compromiso_preserva_actividad_historica_deshabilitada(self):
        actividad = self.crear_actividad('Actividad histórica deshabilitada')
        compromiso = Compromiso.objects.create(
            titulo='Compromiso con relación histórica',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        compromiso.actividades.add(actividad)
        actividad.activo = False
        actividad.save(update_fields=['activo'])
        self.client.force_login(self.coordinador)

        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            {
                'titulo': 'Compromiso editado',
                'descripcion': '',
                'solicitante': '',
                'area_apoyo': '',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': self.responsable.pk,
                'estado': Compromiso.Estado.INGRESADO,
                'observaciones': '',
                'actividades': [],
                'motivo_cambio': '',
            },
        )

        self.assertEqual(respuesta.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.titulo, 'Compromiso editado')
        self.assertIn(actividad, compromiso.actividades.all())

    def test_edicion_audita_transiciones_y_registra_fecha_realizacion(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
            estado=Compromiso.Estado.INGRESADO,
        )
        self.client.force_login(self.coordinador)

        datos = {
            'titulo': compromiso.titulo,
            'descripcion': '',
            'solicitante': '',
            'area_apoyo': '',
            'fecha_hora': '2027-01-01T10:00',
            'responsable': self.responsable.pk,
            'observaciones': '',
            'actividades': [],
            'motivo_cambio': '',
        }
        for estado in (
            Compromiso.Estado.PENDIENTE,
            Compromiso.Estado.EN_PROCESO,
            Compromiso.Estado.REALIZADO,
        ):
            datos['estado'] = estado
            respuesta = self.client.post(reverse('agenda:editar', args=[compromiso.pk]), datos)
            self.assertEqual(respuesta.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.estado, Compromiso.Estado.REALIZADO)
        self.assertIsNotNone(compromiso.fecha_realizacion)
        self.assertEqual(
            HistorialCompromiso.objects.filter(
                compromiso=compromiso,
                campo='estado',
                realizado_por=self.coordinador,
            ).count(),
            3,
        )

    def test_reasignar_requiere_motivo(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        nuevo_responsable = User.objects.create_user(username='func2', password='clave-segura')
        perfil = Perfil.objects.get(usuario=nuevo_responsable)
        perfil.rol = self.responsable.perfil.rol
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        datos = {
            'titulo': compromiso.titulo,
            'descripcion': '',
            'solicitante': '',
            'area_apoyo': '',
            'fecha_hora': '2027-01-01T10:00',
            'responsable': nuevo_responsable.pk,
            'estado': Compromiso.Estado.INGRESADO,
            'observaciones': '',
            'actividades': [],
            'motivo_cambio': '',
        }
        form = CompromisoForm(
            data=datos,
            instance=compromiso,
            user=self.coordinador,
            delegaciones=[self.delegacion],
        )

        self.assertEqual(self.coordinador.perfil.rol_codigo, 'coordinador')
        self.assertNotEqual(nuevo_responsable.pk, compromiso.responsable_id)
        self.assertFalse(form.is_valid(), form.cleaned_data)
        self.assertIn('motivo_cambio', form.errors)
        datos['motivo_cambio'] = 'Reasignación por ausencia del responsable original'
        form = CompromisoForm(
            data=datos,
            instance=compromiso,
            user=self.coordinador,
            delegaciones=[self.delegacion],
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            datos,
        )
        self.assertEqual(respuesta.status_code, 302)
        cambio = HistorialCompromiso.objects.get(
            compromiso=compromiso,
            campo='responsable',
        )
        self.assertEqual(cambio.motivo, datos['motivo_cambio'])
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.responsable, nuevo_responsable)

    def test_evidencia_de_agenda_solo_la_sube_el_responsable_o_jefatura(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        actividad = self.crear_actividad('Preparación')
        compromiso.actividades.add(actividad)
        self.client.force_login(self.responsable)

        respuesta = self.client.get(reverse('agenda:detalle', args=[compromiso.pk]))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Preparación')
        self.assertContains(respuesta, '24/10/2026')
        self.assertContains(respuesta, actividad.get_estado_display())
        self.assertContains(respuesta, actividad.descripcion)
        self.assertContains(respuesta, 'Adjuntar evidencia')
        self.assertFalse(Evidencia.objects.filter(compromiso=compromiso).exists())

    def test_responsable_adjunto_archivo_con_origen_agenda(self):
        from PIL import Image

        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        contenido = BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(contenido, format='PNG')
        archivo = SimpleUploadedFile('respaldo.png', contenido.getvalue(), content_type='image/png')
        self.client.force_login(self.responsable)

        respuesta = self.client.post(
            reverse('evidencias:agenda_crear', args=[compromiso.pk]),
            {'descripcion': 'Registro fotográfico', 'archivos': [archivo]},
        )

        self.assertRedirects(respuesta, reverse('agenda:detalle', args=[compromiso.pk]))
        evidencia = Evidencia.objects.get(compromiso=compromiso)
        self.assertEqual(evidencia.descripcion, 'Registro fotográfico')
        self.assertEqual(evidencia.origen, 'Agenda')


class AgendaRoleAuthorizationTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='AGENDA-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='AGENDA-B', nombre='Delegación B')
        self.roles = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'verificador', 'funcionario'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': f'Agenda {codigo}'},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol
        self.users = {
            codigo: self.crear_usuario(
                f'agenda-{codigo}',
                codigo,
                [self.delegacion_a],
                self.delegacion_a,
            )
            for codigo in self.roles
        }

    def crear_usuario(self, username, codigo_rol, delegaciones, delegacion):
        user = User.objects.create_user(username=username, password='clave-segura')
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = self.roles[codigo_rol]
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set(delegaciones)
        user.perfil = perfil
        return user

    def activar_delegacion(self, user, delegacion):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = delegacion.pk
        session.save()

    def crear_compromiso(self, delegacion, responsable=None, titulo='Compromiso autorizado'):
        return Compromiso.objects.create(
            titulo=titulo,
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=responsable or self.users['funcionario'],
            delegacion=delegacion,
        )

    def datos_gestor(self, compromiso, **overrides):
        datos = {
            'titulo': compromiso.titulo,
            'descripcion': compromiso.descripcion,
            'solicitante': compromiso.solicitante,
            'area_apoyo': compromiso.area_apoyo,
            'fecha_hora': '2027-01-01T10:00',
            'responsable': compromiso.responsable_id,
            'estado': Compromiso.Estado.PENDIENTE,
            'observaciones': compromiso.observaciones,
            'actividades': [],
            'motivo_cambio': '',
        }
        datos.update(overrides)
        return datos

    def test_todos_los_roles_pueden_crear_compromisos(self):
        for codigo, user in self.users.items():
            with self.subTest(rol=codigo):
                self.activar_delegacion(user, self.delegacion_a)
                respuesta = self.client.post(
                    reverse('agenda:crear'),
                    {
                        'titulo': f'Compromiso {codigo}',
                        'descripcion': '',
                        'solicitante': '',
                        'area_apoyo': '',
                        'fecha_hora': '2027-01-01T10:00',
                        'responsable': user.pk,
                        'delegacion': self.delegacion_b.pk,
                        'observaciones': '',
                        'actividades': [],
                        'creado_por': self.users['administrador'].pk,
                    },
                )
                self.assertEqual(respuesta.status_code, 302)
                compromiso = Compromiso.objects.get(titulo=f'Compromiso {codigo}')
                self.assertEqual(compromiso.delegacion, self.delegacion_a)
                self.assertEqual(compromiso.responsable, user)
                self.assertEqual(compromiso.creado_por, user)

    def test_administrador_normal_puede_gestionar_compromiso_de_otra_delegacion(self):
        responsable_b = self.crear_usuario(
            'responsable-b',
            'funcionario',
            [self.delegacion_b],
            self.delegacion_b,
        )
        compromiso = self.crear_compromiso(self.delegacion_b, responsable=responsable_b)
        administrador = self.users['administrador']
        perfil = Perfil.objects.get(usuario=administrador)
        perfil.delegacion = self.delegacion_a
        perfil.save(update_fields=['delegacion'])
        self.activar_delegacion(administrador, self.delegacion_a)

        self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})

        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            self.datos_gestor(compromiso),
        )

        self.assertEqual(respuesta.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.estado, Compromiso.Estado.PENDIENTE)

    def test_delegado_y_coordinador_gestionan_solo_compromisos_de_su_delegacion(self):
        for codigo in ('delegado', 'coordinador'):
            with self.subTest(rol=codigo):
                compromiso_local = self.crear_compromiso(
                    self.delegacion_a,
                    titulo=f'Local {codigo}',
                )
                compromiso_local.creado_por = self.users[codigo]
                compromiso_local.save(update_fields=['creado_por'])
                nuevo_responsable = self.crear_usuario(
                    f'nuevo-responsable-{codigo}',
                    'funcionario',
                    [self.delegacion_a],
                    self.delegacion_a,
                )
                compromiso_ajeno = self.crear_compromiso(
                    self.delegacion_b,
                    titulo=f'Ajeno {codigo}',
                )
                self.activar_delegacion(self.users[codigo], self.delegacion_a)

                local_response = self.client.post(
                    reverse('agenda:editar', args=[compromiso_local.pk]),
                    self.datos_gestor(
                        compromiso_local,
                        responsable=nuevo_responsable.pk,
                        motivo_cambio='Reasignación en la delegación',
                    ),
                )
                ajeno_response = self.client.post(
                    reverse('agenda:editar', args=[compromiso_ajeno.pk]),
                    self.datos_gestor(compromiso_ajeno),
                )

                self.assertEqual(local_response.status_code, 302)
                self.assertEqual(ajeno_response.status_code, 404)
                compromiso_local.refresh_from_db()
                self.assertEqual(compromiso_local.responsable, nuevo_responsable)
                self.assertEqual(compromiso_local.creado_por, self.users[codigo])
                compromiso_ajeno.refresh_from_db()
                self.assertEqual(compromiso_ajeno.estado, Compromiso.Estado.INGRESADO)

    def test_creador_puede_eliminarse_sin_eliminar_compromiso_historico(self):
        compromiso = self.crear_compromiso(
            self.delegacion_a,
            responsable=self.users['funcionario'],
        )
        compromiso.creado_por = self.users['coordinador']
        compromiso.save(update_fields=['creado_por'])

        self.users['coordinador'].delete()

        compromiso.refresh_from_db()
        self.assertIsNone(compromiso.creado_por)
        self.assertEqual(compromiso.responsable, self.users['funcionario'])
        self.assertTrue(Compromiso.objects.filter(pk=compromiso.pk).exists())

    def test_funcionario_y_verificador_responsables_solo_cambian_estado(self):
        for codigo in ('funcionario', 'verificador'):
            with self.subTest(rol=codigo):
                user = self.users[codigo]
                compromiso = self.crear_compromiso(
                    self.delegacion_a,
                    responsable=user,
                    titulo=f'Responsable {codigo}',
                )
                self.activar_delegacion(user, self.delegacion_a)

                respuesta = self.client.post(
                    reverse('agenda:editar', args=[compromiso.pk]),
                    {
                        'estado': Compromiso.Estado.PENDIENTE,
                        'responsable': self.users['coordinador'].pk,
                        'titulo': 'Título manipulado',
                    },
                )

                self.assertEqual(respuesta.status_code, 302)
                compromiso.refresh_from_db()
                self.assertEqual(compromiso.estado, Compromiso.Estado.PENDIENTE)
                self.assertEqual(compromiso.responsable, user)
                self.assertEqual(compromiso.titulo, f'Responsable {codigo}')

    def test_funcionario_y_verificador_no_responsables_no_pueden_modificar(self):
        for codigo in ('funcionario', 'verificador'):
            with self.subTest(rol=codigo):
                compromiso = self.crear_compromiso(
                    self.delegacion_a,
                    responsable=self.users['coordinador'],
                    titulo=f'Ajeno {codigo}',
                )
                self.activar_delegacion(self.users[codigo], self.delegacion_a)

                respuesta = self.client.post(
                    reverse('agenda:editar', args=[compromiso.pk]),
                    {'estado': Compromiso.Estado.PENDIENTE},
                )

                self.assertEqual(respuesta.status_code, 403)
                compromiso.refresh_from_db()
                self.assertEqual(compromiso.estado, Compromiso.Estado.INGRESADO)

    def test_funcionario_y_verificador_pierden_permiso_al_dejar_de_ser_responsables(self):
        for codigo in ('funcionario', 'verificador'):
            with self.subTest(rol=codigo):
                user = self.users[codigo]
                compromiso = self.crear_compromiso(
                    self.delegacion_a,
                    responsable=user,
                    titulo=f'Reasignado {codigo}',
                )
                self.activar_delegacion(user, self.delegacion_a)
                compromiso.responsable = self.users['coordinador']
                compromiso.save(update_fields=['responsable'])

                respuesta = self.client.post(
                    reverse('agenda:editar', args=[compromiso.pk]),
                    {'estado': Compromiso.Estado.PENDIENTE},
                )

                self.assertEqual(respuesta.status_code, 403)
                compromiso.refresh_from_db()
                self.assertEqual(compromiso.estado, Compromiso.Estado.INGRESADO)

    def test_no_administrador_no_puede_crear_compromiso_para_otra_delegacion(self):
        user = self.users['funcionario']
        responsable_ajeno = User.objects.create_user(username='responsable-ajeno', password='clave-segura')
        perfil_ajeno = Perfil.objects.get(usuario=responsable_ajeno)
        perfil_ajeno.rol = self.roles['funcionario']
        perfil_ajeno.delegacion = self.delegacion_b
        perfil_ajeno.save()
        perfil_ajeno.delegaciones.set([self.delegacion_b])
        self.activar_delegacion(user, self.delegacion_a)

        respuesta = self.client.post(
            reverse('agenda:crear'),
            {
                'titulo': 'Creación manipulada',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': responsable_ajeno.pk,
                'actividades': [],
            },
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Compromiso.objects.filter(titulo='Creación manipulada').exists())

    def test_no_administrador_no_puede_editar_compromiso_de_otra_delegacion(self):
        compromiso = self.crear_compromiso(self.delegacion_b)
        self.activar_delegacion(self.users['delegado'], self.delegacion_a)

        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            self.datos_gestor(compromiso, titulo='Edición manipulada'),
        )

        self.assertEqual(respuesta.status_code, 404)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.titulo, 'Compromiso autorizado')


class CompromisosPorDelegacionActivaTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(codigo='FILT-A', nombre='Delegación A')
        self.delegacion_b = Delegacion.objects.create(codigo='FILT-B', nombre='Delegación B')
        self.coordinador = self._crear_usuario('coord-filtro', 'coordinador')
        self.verificador = self._crear_usuario('verif-filtro', 'verificador')
        self.funcionario = self._crear_usuario('func-filtro', 'funcionario')
        self.delegado = self._crear_usuario('deleg-filtro', 'delegado')

        for user in (self.coordinador, self.verificador, self.funcionario, self.delegado):
            user.perfil.delegacion = self.delegacion_a
            user.perfil.save(update_fields=['delegacion'])
            user.perfil.delegaciones.set([self.delegacion_a, self.delegacion_b])

        self.compromiso_a = self._crear_compromiso(
            'Compromiso delegación A', self.delegacion_a, self.coordinador
        )
        self.compromiso_b = self._crear_compromiso(
            'Compromiso delegación B', self.delegacion_b, self.coordinador
        )

        self.administrador = User.objects.create_superuser(
            username='admin-filtro',
            email='admin-filtro@example.com',
            password='clave-segura',
        )

    def _crear_usuario(self, username, codigo_rol):
        rol, _ = Rol.objects.get_or_create(
            codigo=codigo_rol,
            defaults={'nombre': codigo_rol.title()},
        )
        user = User.objects.create_user(username=username, password='clave-segura')
        perfil = user.perfil
        perfil.rol = rol
        perfil.save(update_fields=['rol'])
        return user

    def _crear_compromiso(self, titulo, delegacion, responsable):
        return Compromiso.objects.create(
            titulo=titulo,
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=responsable,
            delegacion=delegacion,
        )

    def _activar_delegacion(self, user, delegacion):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = delegacion.pk
        session.save()

    def test_usuario_ve_solo_compromisos_de_delegacion_activa_y_al_cambiarla(self):
        self._activar_delegacion(self.coordinador, self.delegacion_a)
        respuesta_a = self.client.get(reverse('agenda:lista'))
        self.assertContains(respuesta_a, self.compromiso_a.titulo)
        self.assertNotContains(respuesta_a, self.compromiso_b.titulo)

        session = self.client.session
        session['delegacion_activa_id'] = self.delegacion_b.pk
        session.save()
        respuesta_b = self.client.get(reverse('agenda:lista'))
        self.assertContains(respuesta_b, self.compromiso_b.titulo)
        self.assertNotContains(respuesta_b, self.compromiso_a.titulo)

    def test_administrador_conserva_acceso_global(self):
        self._activar_delegacion(self.administrador, self.delegacion_a)
        self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        respuesta = self.client.get(reverse('agenda:lista'))
        self.assertContains(respuesta, self.compromiso_a.titulo)
        self.assertContains(respuesta, self.compromiso_b.titulo)

    def test_coordinador_respeta_delegacion_activa(self):
        self._activar_delegacion(self.coordinador, self.delegacion_a)
        respuesta = self.client.get(reverse('agenda:lista'))
        self.assertContains(respuesta, self.compromiso_a.titulo)
        self.assertNotContains(respuesta, self.compromiso_b.titulo)

    def test_verificador_funcionario_y_delegado_no_ven_compromiso_ajeno_por_ser_responsables(self):
        for user in (self.verificador, self.funcionario, self.delegado):
            with self.subTest(rol=user.perfil.rol_codigo):
                self._activar_delegacion(user, self.delegacion_a)
                respuesta = self.client.get(reverse('agenda:lista'))
                self.assertContains(respuesta, self.compromiso_a.titulo)
                self.assertNotContains(respuesta, self.compromiso_b.titulo)

    def test_sin_delegacion_activa_no_muestra_compromisos(self):
        self.client.force_login(self.funcionario)
        self.funcionario.perfil.delegacion = None
        self.funcionario.perfil.delegaciones.clear()
        self.funcionario.perfil.save(update_fields=['delegacion'])
        self.compromiso_b.responsable = self.funcionario
        self.compromiso_b.save(update_fields=['responsable'])
        session = self.client.session
        session.pop('delegacion_activa_id', None)
        session.save()

        respuesta = self.client.get(reverse('agenda:lista'))

        self.assertNotContains(respuesta, self.compromiso_a.titulo)
        self.assertNotContains(respuesta, self.compromiso_b.titulo)


class CompromisoDesdeActividadTests(TestCase):
    def setUp(self):
        self.delegacion_a = Delegacion.objects.create(
            codigo='DESDE-A',
            nombre='Delegación Desde A',
        )
        self.delegacion_b = Delegacion.objects.create(
            codigo='DESDE-B',
            nombre='Delegación Desde B',
        )
        self.roles = {}
        for codigo in (
            'administrador',
            'delegado',
            'coordinador',
            'funcionario',
            'verificador',
        ):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': f'Desde {codigo}'},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol

        self.users = {
            codigo: self.crear_usuario(codigo, [self.delegacion_a], self.delegacion_a)
            for codigo in self.roles
        }
        self.responsable_b = self.crear_usuario(
            'responsable-b',
            [self.delegacion_b],
            self.delegacion_b,
        )
        self.tipo = TipoAtencion.objects.create(
            codigo='DESDE-TIPO',
            nombre='Tipo desde actividad',
        )
        self.subatencion = SubAtencion.objects.create(
            codigo='DESDE-SUB',
            nombre='Subcategoría desde actividad',
            tipo=self.tipo,
        )
        self.actividad_a = self.crear_actividad(
            'Actividad delegación A',
            self.delegacion_a,
            creador=self.users['funcionario'],
        )
        self.actividad_b = self.crear_actividad(
            'Actividad delegación B',
            self.delegacion_b,
            creador=self.responsable_b,
        )

    def crear_usuario(self, codigo, delegaciones, predeterminada):
        user = User.objects.create_user(
            username=f'desde-{codigo}',
            password='clave-segura',
        )
        perfil = user.perfil
        perfil.rol = self.roles[codigo] if codigo in self.roles else self.roles['funcionario']
        perfil.delegacion = predeterminada
        perfil.save()
        perfil.delegaciones.set(delegaciones)
        return user

    def crear_actividad(
        self,
        titulo,
        delegacion,
        *,
        creador=None,
        estado=AtencionCiudadana.Estado.REGISTRADA,
        activo=True,
        va_al_tubo=False,
    ):
        return AtencionCiudadana.objects.create(
            titulo=titulo,
            fecha='2026-10-25',
            estado=estado,
            activo=activo,
            solicitante=f'Solicitante {titulo}',
            tipo=self.tipo,
            subatencion=self.subatencion,
            va_al_tubo=va_al_tubo,
            descripcion=f'Descripción {titulo}',
            delegacion=delegacion,
            responsable=creador or self.users['funcionario'],
            creado_por=creador,
        )

    def activar(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session['delegacion_activa_id'] = (delegacion or self.delegacion_a).pk
        session.save()

    def datos_compromiso(self, titulo, responsable, actividades=None, **extra):
        datos = {
            'titulo': titulo,
            'descripcion': 'Descripción del compromiso',
            'solicitante': 'Solicitante',
            'area_apoyo': '',
            'fecha_hora': '2027-01-01T10:00',
            'responsable': responsable.pk,
            'observaciones': '',
            'actividades': [actividad.pk for actividad in (actividades or [])],
            'delegacion': self.delegacion_b.pk,
            'estado': Compromiso.Estado.REALIZADO,
            'creado_por': self.users['administrador'].pk,
        }
        datos.update(extra)
        return datos

    def crear_desde(self, user, actividad, titulo, actividades=None, **extra):
        self.activar(user)
        datos = self.datos_compromiso(
            titulo,
            user,
            actividades,
            **extra,
        )
        return self.client.post(
            reverse('atenciones:agregar_a_agenda', args=[actividad.pk]),
            datos,
        )

    def test_todos_los_roles_agenda_crean_y_origen_se_asocia_sin_alterar_actividad(self):
        for rol, user in self.users.items():
            with self.subTest(rol=rol):
                actividad = self.actividad_b if rol == 'administrador' else self.actividad_a
                responsable = self.responsable_b if rol == 'administrador' else user
                self.activar(user, actividad.delegacion)
                respuesta = self.client.post(
                    reverse('atenciones:agregar_a_agenda', args=[actividad.pk]),
                    self.datos_compromiso(
                        f'Creado por {rol}',
                        responsable,
                        actividades=[],
                    ),
                )
                self.assertEqual(respuesta.status_code, 302)
                compromiso = Compromiso.objects.get(titulo=f'Creado por {rol}')
                self.assertEqual(compromiso.delegacion, actividad.delegacion)
                self.assertEqual(list(compromiso.actividades.all()), [actividad])
                actividad.refresh_from_db()
                self.assertEqual(actividad.estado, AtencionCiudadana.Estado.REGISTRADA)
                self.assertTrue(actividad.activo)
                self.assertFalse(actividad.va_al_tubo)
                self.assertEqual(
                    actividad.creado_por,
                    self.responsable_b if rol == 'administrador' else self.users['funcionario'],
                )

    def test_admin_requiere_contexto_de_actividad_o_global_para_crear_compromiso(self):
        admin = self.users['administrador']
        self.activar(admin, self.delegacion_a)

        respuesta = self.client.post(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_b.pk]),
            self.datos_compromiso('Compromiso territorial admin', self.responsable_b),
        )

        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(Compromiso.objects.filter(titulo='Compromiso territorial admin').exists())
        self.client.post(reverse('usuarios:delegacion_activa'), {'delegacion_id': 'global'})
        respuesta = self.client.post(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_b.pk]),
            self.datos_compromiso('Compromiso territorial admin', self.responsable_b))
        self.assertEqual(respuesta.status_code, 302)
        compromiso = Compromiso.objects.get(titulo='Compromiso territorial admin')
        self.assertEqual(compromiso.delegacion, self.delegacion_b)
        self.assertEqual(compromiso.responsable, self.responsable_b)
        self.assertIn(self.actividad_b, compromiso.actividades.all())

    def test_acceso_directo_rechaza_otra_delegacion_y_usuario_transferido(self):
        for rol in ('funcionario', 'verificador', 'coordinador', 'delegado'):
            with self.subTest(rol=rol):
                self.activar(self.users[rol])
                response = self.client.get(
                    reverse('atenciones:agregar_a_agenda', args=[self.actividad_b.pk])
                )
                self.assertEqual(response.status_code, 404)

        funcionario = self.users['funcionario']
        funcionario.perfil.delegacion = self.delegacion_b
        funcionario.perfil.save(update_fields=['delegacion'])
        funcionario.perfil.delegaciones.set([self.delegacion_b])
        self.activar(funcionario, self.delegacion_a)
        response = self.client.get(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.actividad_a.delegacion, self.delegacion_a)

    def test_creador_ve_origen_y_formulario_fija_delegacion_y_actividad(self):
        self.activar(self.users['funcionario'])
        detalle = self.client.get(
            reverse('atenciones:detalle', args=[self.actividad_a.pk])
        )
        self.assertContains(detalle, 'Agregar a Agenda')
        self.assertContains(
            detalle,
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk]),
        )

        formulario = self.client.get(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk])
        )
        self.assertEqual(formulario.status_code, 200)
        self.assertContains(formulario, 'Creando compromiso desde la actividad:')
        self.assertContains(formulario, 'Actividad delegación A')
        self.assertContains(formulario, str(self.delegacion_a))
        self.assertIn(
            self.actividad_a.pk,
            formulario.context['form'].initial['actividades'],
        )
        self.assertEqual(
            list(formulario.context['form'].fields['actividades'].queryset),
            [self.actividad_a],
        )

    def test_post_manipulado_no_cambia_delegacion_ni_omite_actividad_origen(self):
        user = self.users['coordinador']
        response = self.crear_desde(
            user,
            self.actividad_a,
            'Origen forzado',
            actividades=[],
            delegacion=self.delegacion_b.pk,
        )

        self.assertEqual(response.status_code, 302)
        compromiso = Compromiso.objects.get(titulo='Origen forzado')
        self.assertEqual(compromiso.delegacion, self.delegacion_a)
        self.assertEqual(list(compromiso.actividades.all()), [self.actividad_a])

    def test_actividad_adicional_de_misma_delegacion_se_acepta_y_otra_se_rechaza(self):
        otra_local = self.crear_actividad('Otra local', self.delegacion_a)
        self.activar(self.users['coordinador'])
        respuesta = self.client.post(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk]),
            self.datos_compromiso(
                'Dos actividades',
                self.users['coordinador'],
                [otra_local],
            ),
        )
        self.assertEqual(respuesta.status_code, 302)
        compromiso = Compromiso.objects.get(titulo='Dos actividades')
        self.assertSetEqual(set(compromiso.actividades.all()), {self.actividad_a, otra_local})

        self.activar(self.users['coordinador'])
        cruzada = self.client.post(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk]),
            self.datos_compromiso(
                'Actividad cruzada',
                self.users['coordinador'],
                [self.actividad_b],
            ),
        )
        self.assertEqual(cruzada.status_code, 200)
        self.assertFalse(Compromiso.objects.filter(titulo='Actividad cruzada').exists())

    def test_inactiva_y_cerrada_no_inician_compromisos_hasta_reabrir(self):
        deshabilitada = self.crear_actividad(
            'Histórica inactiva',
            self.delegacion_a,
            activo=False,
        )
        cerrada = self.crear_actividad(
            'Histórica cerrada',
            self.delegacion_a,
            estado=AtencionCiudadana.Estado.CERRADA,
        )
        for actividad in (deshabilitada, cerrada):
            with self.subTest(actividad=actividad.titulo):
                self.activar(self.users['coordinador'])
                response = self.client.get(reverse('atenciones:detalle', args=[actividad.pk]))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Agregar a Agenda')
                rejected = self.client.get(
                    reverse('atenciones:agregar_a_agenda', args=[actividad.pk])
                )
                self.assertEqual(rejected.status_code, 404)

        cerrada.estado = AtencionCiudadana.Estado.EN_PROCESO
        cerrada.save(update_fields=['estado'])
        self.activar(self.users['coordinador'])
        self.assertEqual(
            self.client.get(
                reverse('atenciones:agregar_a_agenda', args=[cerrada.pk])
            ).status_code,
            200,
        )

    def test_detalles_muestran_relacion_bidireccional_y_preservan_historial(self):
        otra_local = self.crear_actividad('Segunda actividad', self.delegacion_a)
        self.activar(self.users['coordinador'])
        sin_compromisos = self.client.get(
            reverse('atenciones:detalle', args=[self.actividad_a.pk])
        )
        self.assertContains(
            sin_compromisos,
            'Esta actividad no tiene compromisos relacionados.',
        )

        compromiso_1 = Compromiso.objects.create(
            titulo='Visita a terreno',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.users['funcionario'],
            delegacion=self.delegacion_a,
        )
        compromiso_2 = Compromiso.objects.create(
            titulo='Reunión de seguimiento',
            fecha_hora='2027-01-02T10:00:00Z',
            responsable=self.users['coordinador'],
            delegacion=self.delegacion_a,
        )
        compromiso_1.actividades.add(self.actividad_a, otra_local)
        compromiso_2.actividades.add(self.actividad_a)
        evidencia_actividad = Evidencia.objects.create(
            atencion=self.actividad_a,
            archivo='evidencias/actividad.png',
            subido_por=self.users['funcionario'],
        )
        evidencia_compromiso = Evidencia.objects.create(
            compromiso=compromiso_1,
            archivo='evidencias/compromiso.png',
            subido_por=self.users['funcionario'],
        )

        self.activar(self.users['coordinador'])
        detalle_actividad = self.client.get(
            reverse('atenciones:detalle', args=[self.actividad_a.pk])
        )
        self.assertContains(detalle_actividad, 'Agenda / Compromisos relacionados')
        self.assertContains(detalle_actividad, 'Visita a terreno')
        self.assertContains(detalle_actividad, 'Reunión de seguimiento')
        self.assertContains(
            detalle_actividad,
            reverse('agenda:detalle', args=[compromiso_1.pk]),
        )

        detalle_compromiso = self.client.get(
            reverse('agenda:detalle', args=[compromiso_1.pk])
        )
        self.assertContains(detalle_compromiso, 'Actividad delegación A')
        self.assertContains(detalle_compromiso, 'Segunda actividad')
        self.assertContains(
            detalle_compromiso,
            reverse('atenciones:detalle', args=[otra_local.pk]),
        )
        self.assertContains(detalle_compromiso, 'Va al tubo: No')

        self.actividad_a.activo = False
        self.actividad_a.estado = AtencionCiudadana.Estado.CERRADA
        self.actividad_a.save(update_fields=['activo', 'estado'])
        self.assertIn(self.actividad_a, compromiso_1.actividades.all())
        self.assertIn(self.actividad_a, compromiso_2.actividades.all())
        detalle_compromiso_historico = self.client.get(
            reverse('agenda:detalle', args=[compromiso_1.pk])
        )
        self.assertContains(detalle_compromiso_historico, 'Actividad delegación A')
        self.assertContains(detalle_compromiso_historico, 'Deshabilitada')
        detalle_actividad_historica = self.client.get(
            reverse('atenciones:detalle', args=[self.actividad_a.pk])
        )
        self.assertContains(detalle_actividad_historica, 'Visita a terreno')
        evidencia_actividad.refresh_from_db()
        evidencia_compromiso.refresh_from_db()
        self.assertEqual(evidencia_actividad.atencion, self.actividad_a)
        self.assertEqual(evidencia_actividad.compromiso, None)
        self.assertEqual(evidencia_compromiso.compromiso, compromiso_1)
        self.assertEqual(evidencia_compromiso.atencion, None)

    def test_creacion_desde_actividad_audita_accion_y_origen(self):
        response = self.crear_desde(
            self.users['coordinador'],
            self.actividad_a,
            'Compromiso auditado',
            actividades=[],
        )

        self.assertEqual(response.status_code, 302)
        compromiso = Compromiso.objects.get(titulo='Compromiso auditado')
        auditoria = RegistroAuditoria.objects.get(
            accion='crear_compromiso_desde_actividad',
            objeto_id=str(compromiso.pk),
        )
        self.assertEqual(auditoria.usuario, self.users['coordinador'])
        self.assertIn(str(self.actividad_a.pk), auditoria.descripcion)
        self.assertIn(self.actividad_a.titulo, auditoria.descripcion)
        self.assertTrue(
            HistorialCompromiso.objects.filter(
                compromiso=compromiso,
                campo='creacion',
                realizado_por=self.users['coordinador'],
            ).exists()
        )

    def test_usuario_sin_rol_agenda_no_puede_usar_el_flujo(self):
        user = User.objects.create_user(
            username='sin-rol-agenda',
            password='clave-segura',
        )
        user.perfil.rol = None
        user.perfil.save(update_fields=['rol'])
        self.activar(user)

        respuesta = self.client.get(
            reverse('atenciones:agregar_a_agenda', args=[self.actividad_a.pk])
        )

        self.assertEqual(respuesta.status_code, 403)
