from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from agenda.models import Compromiso
from atenciones.admin import AtencionCiudadanaAdmin, HistorialEstadoActividadAdmin
from atenciones.estados import cambiar_estado_actividad, registrar_creacion_actividad
from atenciones.forms import AtencionCiudadanaForm
from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from auditoria.models import RegistroAuditoria
from evidencias.models import Evidencia
from sgr.calculos import calcular_avance_indicador
from sgr.models import AporteIndicador
from sgr.test_aportes import DatosAportesMixin


class HistorialEstadoTests(DatosAportesMixin, TestCase):
    def crear(self, rol='funcionario', **extra):
        self.entrar(rol)
        if rol == 'administrador':
            sesion = self.client.session
            sesion['delegacion_activa_id'] = self.a.pk
            sesion.save()
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos_actividad(**extra))
        self.assertEqual(respuesta.status_code, 302)
        return AtencionCiudadana.objects.latest('pk')

    def cambiar(self, actividad, estado, rol='funcionario', **extra):
        self.entrar(rol)
        datos = {'estado': estado, **extra}
        return self.client.post(reverse('atenciones:cambiar_estado', args=[actividad.pk]), datos)

    def test_creacion_registra_evento_actor_y_timestamp_real(self):
        antes = timezone.now()
        actividad = self.crear(fecha='2025-01-01')
        evento = actividad.historial_estados.get()
        self.assertEqual(evento.estado_anterior, '')
        self.assertEqual(evento.estado_nuevo, AtencionCiudadana.Estado.REGISTRADA)
        self.assertEqual(evento.actor, actividad.creado_por)
        self.assertEqual(evento.fecha_hora, actividad.fecha_registro)
        self.assertTrue(timezone.is_aware(evento.fecha_hora))
        self.assertGreaterEqual(evento.fecha_hora, antes)
        self.assertLessEqual(evento.fecha_hora, timezone.now())
        self.assertEqual(actividad.fecha, date(2025, 1, 1))
        self.assertNotEqual(evento.fecha_hora.date(), actividad.fecha)

    def test_creacion_no_admite_estado_actor_ni_timestamp_post(self):
        actividad = self.crear(estado='cerrada', estado_anterior='cerrada', estado_nuevo='en_proceso',
            actor=self.usuarios['administrador'].pk, creado_por=self.usuarios['administrador'].pk,
            fecha_hora='1999-01-01T00:00:00Z', fecha_registro='1999-01-01T00:00:00Z')
        evento = actividad.historial_estados.get()
        self.assertEqual(actividad.estado, AtencionCiudadana.Estado.REGISTRADA)
        self.assertEqual(evento.actor, self.usuarios['funcionario'])
        self.assertNotEqual(evento.fecha_hora.year, 1999)
        form = AtencionCiudadanaForm(request=self.request())
        self.assertTrue({'estado', 'actor', 'fecha_hora', 'fecha_registro', 'estado_anterior',
                         'estado_nuevo'}.isdisjoint(form.fields))

    def test_registro_inicial_idempotente(self):
        actividad = self.crear()
        original = actividad.historial_estados.get()
        repetido = registrar_creacion_actividad(actividad, self.usuarios['funcionario'])
        self.assertEqual(repetido.pk, original.pk)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_inicio_conserva_anterior_actor_y_hora_backend(self):
        actividad = self.crear()
        inicial = actividad.historial_estados.get()
        instante = timezone.now()
        with patch('atenciones.estados.timezone.now', return_value=instante):
            respuesta = self.cambiar(actividad, 'en_proceso', 'coordinador',
                                     fecha_hora='1999-01-01', actor=self.usuarios['funcionario'].pk)
        self.assertEqual(respuesta.status_code, 302)
        evento = actividad.historial_estados.first()
        self.assertEqual(actividad.historial_estados.count(), 2)
        self.assertEqual(evento.estado_anterior, 'registrada')
        self.assertEqual(evento.estado_nuevo, 'en_proceso')
        self.assertEqual(evento.actor, self.usuarios['coordinador'])
        self.assertEqual(evento.fecha_hora, instante)
        self.assertTrue(actividad.historial_estados.filter(pk=inicial.pk).exists())

    def test_cierre_genera_un_solo_evento_adicional(self):
        actividad = self.crear()
        self.assertEqual(self.cambiar(actividad, 'en_proceso').status_code, 302)
        self.assertEqual(self.cambiar(actividad, 'cerrada').status_code, 302)
        self.assertEqual(actividad.historial_estados.count(), 3)
        cierre = actividad.historial_estados.first()
        self.assertEqual((cierre.estado_anterior, cierre.estado_nuevo), ('en_proceso', 'cerrada'))
        self.assertEqual(RegistroAuditoria.objects.filter(accion='cambiar_estado', objeto_id=str(actividad.pk)).count(), 2)

    def test_cinco_eventos_con_reapertura_y_segundo_cierre_orden_determinista(self):
        actividad = self.crear()
        instante = timezone.now()
        with patch('atenciones.estados.timezone.now', return_value=instante):
            for estado, rol in (('en_proceso', 'funcionario'), ('cerrada', 'funcionario'),
                                ('en_proceso', 'delegado'), ('cerrada', 'funcionario')):
                self.assertEqual(self.cambiar(actividad, estado, rol).status_code, 302)
        eventos = list(actividad.historial_estados.all())
        self.assertEqual(len(eventos), 5)
        self.assertEqual([e.estado_nuevo for e in reversed(eventos)],
                         ['registrada', 'en_proceso', 'cerrada', 'en_proceso', 'cerrada'])
        self.assertEqual([e.pk for e in eventos], sorted([e.pk for e in eventos], reverse=True))
        self.assertEqual(eventos[1].actor, self.usuarios['delegado'])

    def test_motivo_opcional_conservado_sin_obligarlo_en_reapertura(self):
        actividad = self.crear()
        self.cambiar(actividad, 'en_proceso', motivo='  Inicio territorial  ')
        self.assertEqual(actividad.historial_estados.first().motivo, 'Inicio territorial')
        self.cambiar(actividad, 'cerrada')
        self.assertEqual(self.cambiar(actividad, 'en_proceso', 'delegado').status_code, 302)
        self.assertEqual(actividad.historial_estados.first().motivo, '')

    def test_guardar_otros_campos_no_crea_falsas_transiciones(self):
        actividad = self.crear()
        actividad.titulo = 'Editado'
        actividad.descripcion = 'Descripción actualizada'
        actividad.responsable = self.usuarios['coordinador']
        actividad.va_al_tubo = True
        actividad.save()
        actividad.save(update_fields=['estado'])
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_mismo_estado_y_transicion_invalida_no_crean_eventos(self):
        actividad = self.crear()
        for estado in ('registrada', 'cerrada', 'inventado'):
            self.assertEqual(self.cambiar(actividad, estado).status_code, 404)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_get_y_csrf_siguen_protegidos(self):
        from django.test import Client
        actividad = self.crear()
        url = reverse('atenciones:cambiar_estado', args=[actividad.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['funcionario'])
        self.assertEqual(cliente.post(url, {'estado': 'en_proceso'}).status_code, 403)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_cada_rol_autorizado_deja_identidad_real(self):
        for rol in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            actividad = self.crear(rol, titulo=f'Actividad {rol}')
            self.assertEqual(self.cambiar(actividad, 'en_proceso', rol).status_code, 302)
            self.assertEqual(actividad.historial_estados.first().actor, self.usuarios[rol])
        actividad = self.crear()
        self.cambiar(actividad, 'en_proceso', 'administrador')
        self.assertNotEqual(actividad.historial_estados.first().actor, actividad.creado_por)

    def test_reglas_de_propiedad_y_reapertura_operativa_no_cambian(self):
        actividad = self.crear()
        self.assertEqual(self.cambiar(actividad, 'en_proceso', 'verificador').status_code, 404)
        self.cambiar(actividad, 'en_proceso')
        self.cambiar(actividad, 'cerrada')
        self.assertEqual(self.cambiar(actividad, 'en_proceso').status_code, 404)
        self.assertEqual(actividad.historial_estados.count(), 3)

    def test_deshabilitada_no_cambia_estado_ni_agrega_eventos(self):
        actividad = self.crear()
        actividad.activo = False
        actividad.save(update_fields=['activo'])
        self.assertEqual(self.cambiar(actividad, 'en_proceso', 'administrador').status_code, 404)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_va_al_tubo_y_disponibilidad_no_generan_transiciones(self):
        actividad = self.crear()
        url = reverse('atenciones:cambiar_va_al_tubo', args=[actividad.pk])
        self.assertEqual(self.client.post(url, {'va_al_tubo': 'true'}).status_code, 302)
        self.entrar('delegado')
        url = reverse('atenciones:cambiar_disponibilidad', args=[actividad.pk])
        for activo in ('false', 'true'):
            self.assertEqual(self.client.post(url, {'activo': activo}).status_code, 302)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_agregar_evidencia_no_genera_transicion(self):
        actividad = self.crear()
        contenido = BytesIO()
        Image.new('RGB', (2, 2), color='white').save(contenido, format='JPEG')
        archivo = SimpleUploadedFile('respaldo.jpg', contenido.getvalue(), content_type='image/jpeg')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            respuesta = self.client.post(reverse('evidencias:atencion_crear', args=[actividad.pk]),
                                         {'archivos': [archivo]})
            self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_agregar_a_agenda_no_genera_transicion(self):
        actividad = self.crear()
        self.entrar('coordinador')
        respuesta = self.client.post(reverse('atenciones:agregar_a_agenda', args=[actividad.pk]), {
            'titulo': 'Compromiso relacionado', 'fecha_hora': '2027-01-01T10:00',
            'responsable': self.usuarios['funcionario'].pk, 'actividades': [actividad.pk],
        })
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(Compromiso.objects.filter(actividades=actividad).exists())
        self.assertEqual(actividad.historial_estados.count(), 1)

    def test_historial_en_detalle_hereda_permisos_y_no_genera_auditoria(self):
        actividad = self.crear()
        self.cambiar(actividad, 'en_proceso', 'coordinador', motivo='Inicio comprobable')
        auditorias = RegistroAuditoria.objects.count()
        for rol in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            self.entrar(rol)
            respuesta = self.client.get(reverse('atenciones:detalle', args=[actividad.pk]))
            self.assertContains(respuesta, 'Historial de estados')
            self.assertContains(respuesta, 'Inicio comprobable')
            self.assertFalse(respuesta.context['historial_estados_incompleto'])
        self.assertEqual(RegistroAuditoria.objects.count(), auditorias)
        self.usuarios['delegado'].perfil.delegaciones.set([self.b])
        self.usuarios['delegado'].perfil.delegacion = self.b
        self.usuarios['delegado'].perfil.save()
        self.entrar('delegado')
        respuesta = self.client.get(reverse('atenciones:detalle', args=[actividad.pk]))
        self.assertEqual(respuesta.status_code, 404)
        self.assertNotContains(respuesta, 'Inicio comprobable', status_code=404)

    def test_creacion_admin_registra_evento_edicion_no_lo_duplica(self):
        model_admin = AtencionCiudadanaAdmin(AtencionCiudadana, admin.site)
        actividad = AtencionCiudadana(titulo='Creada por Admin', fecha=date(2026, 10, 23),
            solicitante='Solicitante', tipo=self.tipo, subatencion=self.sub, descripcion='Detalle',
            delegacion=self.a, responsable=self.usuarios['funcionario'])
        request = self.request('administrador')
        model_admin.save_model(request, actividad, None, change=False)
        evento = actividad.historial_estados.get()
        self.assertEqual(evento.actor, request.user)
        self.assertEqual(evento.actor, actividad.creado_por)
        self.assertEqual(evento.estado_nuevo, 'registrada')
        self.assertEqual(evento.fecha_hora, actividad.fecha_registro)
        actividad.titulo = 'Edición segura'
        model_admin.save_model(request, actividad, None, change=True)
        self.assertEqual(actividad.historial_estados.count(), 1)
        self.assertIn('estado', model_admin.get_readonly_fields(request, actividad))

    def test_admin_historial_solo_lectura_y_filtrado_territorial(self):
        actividad = self.crear()
        model_admin = HistorialEstadoActividadAdmin(HistorialEstadoActividad, admin.site)
        request = self.request('delegado')
        evento = actividad.historial_estados.get()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, evento))
        self.assertFalse(model_admin.has_delete_permission(request, evento))
        self.assertIn('fecha_hora', model_admin.get_readonly_fields(request, evento))
        self.assertIn(evento, model_admin.get_queryset(request))
        request.user.perfil.delegaciones.set([self.b])
        request.user.perfil.delegacion = self.b
        request.user.perfil.save()
        self.assertFalse(model_admin.get_queryset(request).exists())

    def test_actor_eliminado_conserva_evento(self):
        actividad = self.crear()
        self.cambiar(actividad, 'en_proceso', 'coordinador')
        evento = actividad.historial_estados.first()
        self.usuarios['coordinador'].delete()
        evento.refresh_from_db()
        self.assertIsNone(evento.actor)
        self.assertEqual(evento.estado_nuevo, 'en_proceso')

    def test_no_backfill_historico_y_primera_transicion_exacta(self):
        actividad = self.actividad
        antigua = timezone.now() - timedelta(days=90)
        AtencionCiudadana.objects.filter(pk=actividad.pk).update(fecha_registro=antigua)
        actividad.refresh_from_db()
        actividad.descripcion = 'Edición de datos antiguos'
        actividad.save()
        self.assertFalse(actividad.historial_estados.exists())
        self.assertEqual(self.cambiar(actividad, 'en_proceso', 'delegado').status_code, 302)
        evento = actividad.historial_estados.get()
        self.assertEqual((evento.estado_anterior, evento.estado_nuevo), ('cerrada', 'en_proceso'))
        self.assertGreater(evento.fecha_hora, antigua)
        self.entrar('delegado')
        respuesta = self.client.get(reverse('atenciones:detalle', args=[actividad.pk]))
        self.assertTrue(respuesta.context['historial_estados_incompleto'])
        self.assertContains(respuesta, 'sin reconstruir fechas anteriores')

    def test_reapertura_conserva_9d_y_avance_9e(self):
        actividad = self.crear(indicador=self.indicador_a.pk, valor_declarado='20')
        self.cambiar(actividad, 'en_proceso')
        self.cambiar(actividad, 'cerrada')
        Evidencia.objects.create(atencion=actividad, estado=Evidencia.Estado.APROBADA,
            subido_por=self.usuarios['funcionario'], archivo='historia.jpg')
        aporte = AporteIndicador.objects.get(actividad=actividad)
        self.decidir(aporte)
        self.assertEqual(calcular_avance_indicador(self.indicador_a).puntos_ponderados, 1)
        self.cambiar(actividad, 'en_proceso', 'delegado')
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertTrue(aporte.espera_cierre)
        self.assertIsNone(aporte.validado_por)
        self.assertEqual(aporte.historial.filter(accion='reiniciar_aporte_reapertura').count(), 1)
        self.assertEqual(aporte.historial.filter(accion='validar_aporte').count(), 1)
        self.assertEqual(calcular_avance_indicador(self.indicador_a).puntos_ponderados, Decimal('0'))
        self.cambiar(actividad, 'cerrada')
        self.assertEqual(actividad.historial_estados.count(), 5)
        self.assertEqual(calcular_avance_indicador(self.indicador_a).puntos_ponderados, 1)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)

    def test_error_al_crear_evento_revierte_estado_y_auditoria(self):
        actividad = self.crear()
        auditorias = RegistroAuditoria.objects.count()
        with patch('atenciones.estados.HistorialEstadoActividad.objects.create', side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError):
                cambiar_estado_actividad(self.request(), actividad.pk, 'en_proceso')
        actividad.refresh_from_db()
        self.assertEqual(actividad.estado, 'registrada')
        self.assertEqual(actividad.historial_estados.count(), 1)
        self.assertEqual(RegistroAuditoria.objects.count(), auditorias)

    def test_error_reinicio_aporte_revierte_reapertura_e_historial(self):
        with patch('atenciones.estados.reiniciar_por_reapertura', side_effect=RuntimeError('Fallo simulado')):
            with self.assertRaises(RuntimeError):
                cambiar_estado_actividad(self.request('delegado'), self.actividad.pk, 'en_proceso')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'cerrada')
        self.assertFalse(self.actividad.historial_estados.exists())

    def test_error_creando_aporte_no_deja_evento_inicial_huerfano(self):
        with patch('atenciones.views.proponer_aporte', side_effect=ValidationError('Fallo simulado')):
            self.entrar('funcionario')
            respuesta = self.client.post(reverse('atenciones:crear'), self.datos_actividad(
                indicador=self.indicador_a.pk, valor_declarado='20'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(AtencionCiudadana.objects.filter(titulo='Actividad nueva').exists())
        self.assertFalse(HistorialEstadoActividad.objects.exists())

    def test_restricciones_estados_reales_y_no_autotransiciones(self):
        for anterior, nuevo in (('inventado', 'cerrada'), ('registrada', 'inventado'),
                                ('en_proceso', 'en_proceso')):
            with self.subTest(anterior=anterior, nuevo=nuevo), self.assertRaises(IntegrityError), transaction.atomic():
                HistorialEstadoActividad.objects.create(actividad=self.actividad,
                    estado_anterior=anterior, estado_nuevo=nuevo, actor=self.usuarios['funcionario'])
