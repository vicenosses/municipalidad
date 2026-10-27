from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from catalogos.models import SubAtencion, TipoAtencion
from usuarios.models import Delegacion, Perfil, Rol, SolicitudTransferencia
from usuarios.sesion import DELEGACION_SESION, get_delegacion_activa
from usuarios.transferencias import (
    CompromisosPendientesError,
    aplicar_transferencia,
    contar_compromisos_activos,
)


User = get_user_model()


class TransferenciaUsuarioTests(TestCase):
    def setUp(self):
        self.origen = Delegacion.objects.create(nombre='Delegación Norte')
        self.destino = Delegacion.objects.create(nombre='Delegación Centro')
        self.tercera = Delegacion.objects.create(nombre='Delegación Sur')
        self.roles = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            rol, _ = Rol.objects.get_or_create(
                codigo=codigo,
                defaults={'nombre': codigo.title()},
            )
            rol.activo = True
            rol.save(update_fields=['activo'])
            self.roles[codigo] = rol

        self.admin = self.crear_usuario('admin-transfer', 'administrador', self.origen)
        self.delegado = self.crear_usuario('delegado-transfer', 'delegado', self.origen)
        self.delegado_otro = self.crear_usuario('delegado-sur', 'delegado', self.tercera)
        self.coordinador = self.crear_usuario('coordinador-transfer', 'coordinador', self.origen)
        self.coordinador_sur = self.crear_usuario(
            'coordinador-sur',
            'coordinador',
            self.tercera,
        )
        self.funcionario = self.crear_usuario(
            'funcionario-transfer',
            'funcionario',
            self.origen,
            delegaciones=[self.origen, self.tercera],
        )
        self.verificador = self.crear_usuario('verificador-transfer', 'verificador', self.origen)
        self.tipo = TipoAtencion.objects.create(codigo='TRANSFER-TIPO', nombre='Tipo general')
        self.subtipo = SubAtencion.objects.create(
            codigo='TRANSFER-SUB',
            nombre='Subtipo general',
            tipo=self.tipo,
        )

    def crear_usuario(self, username, rol, delegacion, delegaciones=None):
        user = User.objects.create_user(
            username=username,
            first_name='Juan',
            last_name='Pérez',
            password='clave-segura',
        )
        perfil = Perfil.objects.get(usuario=user)
        perfil.rol = self.roles[rol]
        perfil.delegacion = delegacion
        perfil.save()
        perfil.delegaciones.set(delegaciones or [delegacion])
        return user

    def login(self, user, delegacion=None):
        self.client.force_login(user)
        session = self.client.session
        session[DELEGACION_SESION] = (
            'global' if user == self.admin and delegacion is None else (delegacion or self.origen).pk)
        session.save()

    def solicitar(self, solicitante=None, usuario=None, destino=None, origen=None):
        solicitante = solicitante or self.coordinador
        usuario = usuario or self.funcionario
        origen = origen or self.origen
        destino = destino or self.destino
        self.login(solicitante, origen)
        response = self.client.post(
            reverse('usuarios:transferencia_solicitar'),
            {
                'usuario': usuario.pk,
                'delegacion_destino': destino.pk,
                'motivo': 'Cambio de funciones',
            },
        )
        return response, SolicitudTransferencia.objects.filter(usuario=usuario).latest('pk')

    def decidir(self, actor, solicitud, accion='aprobar', **extra):
        self.login(
            actor,
            self.tercera if actor == self.delegado_otro else self.origen,
        )
        return self.client.post(
            reverse('usuarios:transferencia_decidir', args=[solicitud.pk]),
            {'accion': accion, **extra},
        )

    def crear_actividad(self, creador=None, delegacion=None):
        return AtencionCiudadana.objects.create(
            titulo='Actividad histórica',
            fecha='2026-10-25',
            solicitante='Solicitante',
            tipo=self.tipo,
            subatencion=self.subtipo,
            descripcion='Registro histórico',
            delegacion=delegacion or self.origen,
            responsable=creador or self.funcionario,
            creado_por=creador,
        )

    def crear_compromiso(self, responsable):
        return Compromiso.objects.create(
            titulo='Compromiso pendiente',
            fecha_hora=timezone.now() + timedelta(days=1),
            responsable=responsable,
            delegacion=self.origen,
        )

    def test_coordinador_solicita_usuario_de_su_delegacion_y_queda_pendiente_auditado(self):
        response, solicitud = self.solicitar()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.PENDIENTE)
        self.assertEqual(solicitud.delegacion_origen, self.origen)
        self.assertEqual(solicitud.delegacion_destino, self.destino)
        self.assertEqual(solicitud.solicitante, self.coordinador)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='solicitar_transferencia',
                objeto_id=str(solicitud.pk),
            ).exists()
        )

    def test_coordinador_no_puede_solicitar_usuario_ajeno(self):
        usuario_ajeno = self.crear_usuario('externo-transfer', 'funcionario', self.tercera)
        self.login(self.coordinador)
        response = self.client.post(
            reverse('usuarios:transferencia_solicitar'),
            {
                'usuario': usuario_ajeno.pk,
                'delegacion_destino': self.destino.pk,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(SolicitudTransferencia.objects.exists())

    def test_coordinador_no_puede_aprobar_ni_rechazar(self):
        _, solicitud = self.solicitar()
        self.login(self.coordinador)

        for accion in ('aprobar', 'rechazar'):
            with self.subTest(accion=accion):
                response = self.client.post(
                    reverse('usuarios:transferencia_decidir', args=[solicitud.pk]),
                    {'accion': accion},
                )
                self.assertEqual(response.status_code, 403)

        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.PENDIENTE)

    def test_delegado_aprueba_y_rechaza_solicitudes_de_su_delegacion_con_trazabilidad(self):
        _, aprobada = self.solicitar(usuario=self.funcionario)
        _, rechazada = self.solicitar(
            usuario=self.crear_usuario('funcionario-rechazado', 'funcionario', self.origen),
        )

        response = self.decidir(self.delegado, aprobada)
        self.assertEqual(response.status_code, 302)
        aprobada.refresh_from_db()
        self.assertEqual(aprobada.estado, SolicitudTransferencia.Estado.APROBADA)
        self.assertEqual(aprobada.decidido_por, self.delegado)
        self.assertIsNotNone(aprobada.fecha_decision)
        self.assertEqual(aprobada.usuario.perfil.delegacion, self.destino)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='aprobar_transferencia',
                objeto_id=str(aprobada.pk),
            ).exists()
        )

        response = self.decidir(self.delegado, rechazada, accion='rechazar')
        self.assertEqual(response.status_code, 302)
        rechazada.refresh_from_db()
        self.assertEqual(rechazada.estado, SolicitudTransferencia.Estado.RECHAZADA)
        self.assertEqual(rechazada.decidido_por, self.delegado)
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='rechazar_transferencia',
                objeto_id=str(rechazada.pk),
            ).exists()
        )

    def test_delegado_no_puede_consultar_ni_decidir_solicitud_de_otra_delegacion(self):
        usuario_sur = self.crear_usuario('funcionario-sur', 'funcionario', self.tercera)
        _, solicitud = self.solicitar(
            solicitante=self.coordinador_sur,
            usuario=usuario_sur,
            origen=self.tercera,
        )
        self.login(self.delegado_otro, self.tercera)

        response = self.client.get(
            reverse('usuarios:transferencia_decidir', args=[solicitud.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.login(self.delegado)
        response = self.client.post(
            reverse('usuarios:transferencia_decidir', args=[solicitud.pk]),
            {'accion': 'aprobar'},
        )
        self.assertEqual(response.status_code, 404)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.PENDIENTE)

    def test_administrador_consulta_solicitudes_de_todas_las_delegaciones(self):
        _, solicitud_origen = self.solicitar()
        usuario_sur = self.crear_usuario('funcionario-solicitud-sur', 'funcionario', self.tercera)
        _, solicitud_sur = self.solicitar(
            solicitante=self.coordinador_sur,
            usuario=usuario_sur,
            origen=self.tercera,
        )
        self.login(self.admin)

        response = self.client.get(reverse('usuarios:transferencias'))

        mostradas = {item.pk for item in response.context['solicitudes']}
        self.assertEqual(mostradas, {solicitud_origen.pk, solicitud_sur.pk})

    def test_administrador_puede_aprobar_y_rechazar_solicitudes(self):
        _, aprobada = self.solicitar()
        _, rechazada = self.solicitar(
            usuario=self.crear_usuario('funcionario-admin-rechazo', 'funcionario', self.origen),
        )

        self.assertEqual(self.decidir(self.admin, aprobada).status_code, 302)
        self.assertEqual(
            self.decidir(self.admin, rechazada, accion='rechazar').status_code,
            302,
        )
        aprobada.refresh_from_db()
        rechazada.refresh_from_db()
        self.assertEqual(aprobada.estado, SolicitudTransferencia.Estado.APROBADA)
        self.assertEqual(rechazada.estado, SolicitudTransferencia.Estado.RECHAZADA)

    def test_delegado_transfiere_directamente_solo_usuario_de_su_delegacion(self):
        self.login(self.delegado)
        url = reverse('usuarios:transferencia_directa', args=[self.funcionario.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(
            url,
            {'delegacion_destino': self.destino.pk, 'motivo': 'Reasignación'},
        )
        self.assertEqual(response.status_code, 302)
        perfil = self.funcionario.perfil
        perfil.refresh_from_db()
        self.assertEqual(perfil.delegacion, self.destino)
        self.assertFalse(perfil.delegaciones.filter(pk=self.origen.pk).exists())
        self.assertTrue(perfil.delegaciones.filter(pk=self.destino.pk).exists())
        self.assertTrue(perfil.delegaciones.filter(pk=self.tercera.pk).exists())
        self.assertTrue(
            RegistroAuditoria.objects.filter(
                accion='transferencia_directa',
                objeto_id=str(self.funcionario.pk),
            ).exists()
        )

        usuario_ajeno = self.crear_usuario('funcionario-ajeno', 'funcionario', self.tercera)
        response = self.client.get(
            reverse('usuarios:transferencia_directa', args=[usuario_ajeno.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_administrador_transfiere_globalmente(self):
        usuario_ajeno = self.crear_usuario('funcionario-global', 'funcionario', self.tercera)
        self.login(self.admin)

        response = self.client.post(
            reverse('usuarios:transferencia_directa', args=[usuario_ajeno.pk]),
            {'delegacion_destino': self.destino.pk},
        )

        self.assertEqual(response.status_code, 302)
        usuario_ajeno.perfil.refresh_from_db()
        self.assertEqual(usuario_ajeno.perfil.delegacion, self.destino)

    def test_funcionario_y_verificador_no_pueden_solicitar_ni_transferir(self):
        for usuario in (self.funcionario, self.verificador):
            with self.subTest(usuario=usuario.username):
                self.login(usuario)
                response = self.client.get(reverse('usuarios:transferencia_solicitar'))
                self.assertEqual(response.status_code, 403)
                response = self.client.get(
                    reverse('usuarios:transferencia_directa', args=[self.funcionario.pk])
                )
                self.assertEqual(response.status_code, 403)

    def test_transferencia_invalida_delegacion_sesion_y_conserva_otras_autorizaciones(self):
        self.login(self.delegado)
        self.client.post(
            reverse('usuarios:transferencia_directa', args=[self.funcionario.pk]),
            {'delegacion_destino': self.destino.pk},
        )
        request = RequestFactory().get('/')
        request.user = self.funcionario
        request.session = {DELEGACION_SESION: self.origen.pk}

        self.assertEqual(get_delegacion_activa(request), self.destino)
        self.assertNotIn(DELEGACION_SESION, request.session)
        self.assertTrue(self.funcionario.perfil.delegaciones.filter(pk=self.tercera.pk).exists())

    def test_actividad_historica_y_creador_no_cambian_y_creador_se_muestra_ex_funcionario(self):
        actividad = self.crear_actividad(self.funcionario)
        creador_original = actividad.creado_por_id
        self.login(self.delegado)
        self.client.post(
            reverse('usuarios:transferencia_directa', args=[self.funcionario.pk]),
            {'delegacion_destino': self.destino.pk},
        )
        actividad.refresh_from_db()

        self.assertEqual(actividad.delegacion, self.origen)
        self.assertEqual(actividad.creado_por_id, creador_original)
        self.assertEqual(actividad.creador_historico_display, 'Ex funcionario Juan Pérez')
        actividad.delegacion = self.destino
        actividad.save()
        actividad.refresh_from_db()
        self.assertEqual(actividad.delegacion, self.origen)
        self.assertEqual(actividad.creado_por_id, creador_original)
        self.assertContains(
            self.client.get(reverse('atenciones:detalle', args=[actividad.pk])),
            'Ex funcionario Juan Pérez',
        )
        self.assertContains(
            self.client.get(reverse('atenciones:lista')),
            'Ex funcionario Juan Pérez',
        )

    def test_creador_que_aun_esta_autorizado_y_creador_nulo_se_muestran_seguros(self):
        actividad = self.crear_actividad(self.funcionario)
        self.assertEqual(actividad.creador_historico_display, 'Juan Pérez')
        sin_creador = self.crear_actividad()
        self.assertEqual(
            sin_creador.creador_historico_display,
            'Usuario histórico/no disponible',
        )

    def test_actividad_nueva_tras_transferencia_usa_la_delegacion_destino(self):
        self.login(self.delegado)
        self.client.post(
            reverse('usuarios:transferencia_directa', args=[self.funcionario.pk]),
            {'delegacion_destino': self.destino.pk},
        )
        self.login(self.funcionario)

        response = self.client.post(
            reverse('atenciones:crear'),
            {
                'titulo': 'Actividad nueva',
                'fecha': '2026-10-25',
                'solicitante': 'Solicitante',
                'tipo': self.tipo.pk,
                'subatencion': self.subtipo.pk,
                'descripcion': 'Descripción nueva',
            },
        )

        self.assertEqual(response.status_code, 302)
        nueva = AtencionCiudadana.objects.get(titulo='Actividad nueva')
        self.assertEqual(nueva.delegacion, self.destino)
        self.assertEqual(nueva.creado_por, self.funcionario)

    def test_compromisos_activos_exigen_confirmacion_y_no_se_reasignan(self):
        compromiso = self.crear_compromiso(self.funcionario)
        self.assertEqual(contar_compromisos_activos(self.funcionario), 1)
        self.login(self.delegado)
        url = reverse('usuarios:transferencia_directa', args=[self.funcionario.pk])

        response = self.client.post(url, {'delegacion_destino': self.destino.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1')
        self.funcionario.perfil.refresh_from_db()
        self.assertEqual(self.funcionario.perfil.delegacion, self.origen)

        response = self.client.post(
            url,
            {
                'delegacion_destino': self.destino.pk,
                'confirmar_compromisos': 'on',
                'motivo': 'Confirmada con agenda activa',
            },
        )
        self.assertEqual(response.status_code, 302)
        compromiso.refresh_from_db()
        self.funcionario.perfil.refresh_from_db()
        self.assertEqual(self.funcionario.perfil.delegacion, self.destino)
        self.assertEqual(compromiso.responsable, self.funcionario)
        self.assertEqual(compromiso.delegacion, self.origen)
        audit = RegistroAuditoria.objects.get(
            accion='transferencia_directa',
            objeto_id=str(self.funcionario.pk),
        )
        self.assertIn('Compromisos activos al transferir: 1', audit.descripcion)

    def test_aprobacion_con_compromisos_requiere_confirmacion(self):
        self.crear_compromiso(self.funcionario)
        _, solicitud = self.solicitar()

        response = self.decidir(self.delegado, solicitud, accion='aprobar')
        self.assertEqual(response.status_code, 200)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.PENDIENTE)
        self.funcionario.perfil.refresh_from_db()
        self.assertEqual(self.funcionario.perfil.delegacion, self.origen)

        response = self.decidir(
            self.delegado,
            solicitud,
            accion='aprobar',
            confirmar_compromisos='on',
        )
        self.assertEqual(response.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.APROBADA)

    def test_transferencia_no_permite_alterar_origen_destino_o_estado_de_solicitud_por_post(self):
        _, solicitud = self.solicitar()
        self.login(self.delegado)
        response = self.client.post(
            reverse('usuarios:transferencia_decidir', args=[solicitud.pk]),
            {
                'accion': 'aprobar',
                'delegacion_origen': self.tercera.pk,
                'delegacion_destino': self.origen.pk,
                'estado': 'rechazada',
            },
        )
        self.assertEqual(response.status_code, 302)
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.delegacion_origen, self.origen)
        self.assertEqual(solicitud.delegacion_destino, self.destino)
        self.assertEqual(solicitud.estado, SolicitudTransferencia.Estado.APROBADA)

    def test_helper_rechaza_origen_obsoleto_y_destino_igual(self):
        with self.assertRaises(ValidationError):
            aplicar_transferencia(
                self.funcionario,
                self.destino,
                self.tercera,
                False,
            )
        with self.assertRaises(ValidationError):
            aplicar_transferencia(
                self.funcionario,
                self.origen,
                self.origen,
                False,
            )

    def test_compromisos_finalizados_no_cuentan_como_activos(self):
        compromiso = self.crear_compromiso(self.funcionario)
        compromiso.estado = Compromiso.Estado.REALIZADO
        compromiso.save(update_fields=['estado'])

        self.assertEqual(contar_compromisos_activos(self.funcionario), 0)
        self.assertEqual(
            aplicar_transferencia(
                self.funcionario,
                self.origen,
                self.destino,
                False,
            ),
            0,
        )
