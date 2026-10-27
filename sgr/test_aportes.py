from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.models import Evidencia
from sgr.aportes import (
    indicadores_para_actividad, pendientes_validacion, puede_proponer, proponer_aporte, validar_aporte,
)
from sgr.models import AporteIndicador, EventoAporte, HistorialObjetivoIndicador, Indicador
from sgr.plazos import dentro_plazo, limite_asociacion
from sgr.test_indicadores import DatosIndicadoresMixin
from usuarios.models import Perfil


class DatosAportesMixin(DatosIndicadoresMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tipo = TipoAtencion.objects.create(codigo='AP', nombre='Tipo aporte')
        cls.sub = SubAtencion.objects.create(tipo=cls.tipo, nombre='Sub aporte')
        cls.actividad = AtencionCiudadana.objects.create(
            titulo='Actividad con aporte', fecha=date(2026, 10, 23), solicitante='Vecino',
            tipo=cls.tipo, subatencion=cls.sub, descripcion='Trabajo territorial',
            delegacion=cls.a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'],
            estado=AtencionCiudadana.Estado.CERRADA,
        )
        cls.otro_indicador = Indicador.objects.create(meta=cls.meta_a, nombre='Otra medición',
            unidad_medida='otra', unidad_personalizada='árboles', sentido='mayor', valor_objetivo=100)
        segundo = get_user_model().objects.create_user(username='verificador_dos')
        Perfil.objects.filter(usuario=segundo).update(rol=cls.usuarios['verificador'].perfil.rol, delegacion=cls.a)
        segundo.refresh_from_db()
        segundo.perfil.delegaciones.add(cls.a)
        cls.usuarios['verificador_dos'] = segundo

    def setUp(self):
        self.fecha_patch = patch('sgr.plazos.timezone.localdate', return_value=date(2026, 10, 26))
        self.fecha_patch.start()
        self.addCleanup(self.fecha_patch.stop)

    def request(self, rol='funcionario'):
        request = RequestFactory().post('/')
        request.user = self.usuarios[rol]
        request.session = {'delegacion_activa_id': self.a.pk}
        return request

    def asociar(self, indicador=None, valor=Decimal('20')):
        return proponer_aporte(self.request(), self.actividad, indicador or self.indicador_a, valor)

    def evidencia(self, estado=Evidencia.Estado.APROBADA):
        return Evidencia.objects.create(atencion=self.actividad, estado=estado,
            subido_por=self.usuarios['funcionario'], archivo='prueba-aporte.jpg')

    def decidir(self, aporte, rol='verificador', **kwargs):
        datos = dict(estado=AporteIndicador.Estado.CUMPLE)
        datos.update(kwargs)
        return validar_aporte(self.request(rol), aporte.pk, aporte.version, **datos)

    def url_aporte(self):
        return reverse('sgr:aporte_proponer', args=[self.actividad.pk])

    def datos_actividad(self, **kwargs):
        datos = dict(titulo='Actividad nueva', fecha='2026-10-23', solicitante='Vecino nuevo',
                     tipo=self.tipo.pk, subatencion=self.sub.pk, descripcion='Trabajo', va_al_tubo=False)
        datos.update(kwargs)
        return datos


class PlazoAporteTests(TestCase):
    def test_viernes_fin_de_semana_no_consume_plazo(self):
        self.assertEqual(limite_asociacion(date(2026, 10, 23)), date(2026, 10, 28))
        for hoy in (date(2026, 10, 23), date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 28)):
            self.assertTrue(dentro_plazo(date(2026, 10, 23), hoy))
        self.assertFalse(dentro_plazo(date(2026, 10, 23), date(2026, 10, 29)))

    def test_inicio_sabado_domingo_y_fecha_futura(self):
        self.assertEqual(limite_asociacion(date(2026, 10, 24)), date(2026, 10, 28))
        self.assertEqual(limite_asociacion(date(2026, 10, 25)), date(2026, 10, 28))
        self.assertFalse(dentro_plazo(date(2026, 10, 26), date(2026, 10, 25)))


class AporteReglasTests(DatosAportesMixin, TestCase):
    def test_asociacion_unica_estados_valores_e_historial(self):
        aporte = self.asociar()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertEqual(aporte.valor_declarado, Decimal('20'))
        self.assertIsNone(aporte.valor_validado)
        self.assertEqual(aporte.historial.count(), 2)
        evento = aporte.historial.get(accion='asociar_indicador')
        self.assertEqual(evento.indicador_nuevo, self.indicador_a)
        self.assertEqual(evento.declarado_nuevo, Decimal('20'))
        self.assertEqual(evento.usuario, self.usuarios['funcionario'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AporteIndicador.objects.create(actividad=self.actividad, indicador=self.otro_indicador)

    def test_modelo_rechaza_estado_invalido_y_negativos(self):
        aporte = AporteIndicador(actividad=self.actividad, indicador=self.indicador_a,
                                 estado='inventado', valor_declarado=-1, valor_validado=-2)
        with self.assertRaises(ValidationError):
            aporte.full_clean()

    def test_limites_periodo_y_seleccion_territorial(self):
        for fecha in (date(2026, 1, 1), date(2026, 12, 31)):
            self.assertIn(self.indicador_a, indicadores_para_actividad(fecha, self.a))
            self.assertNotIn(self.indicador_b, indicadores_para_actividad(fecha, self.a))
        self.assertFalse(indicadores_para_actividad(date(2025, 12, 31), self.a).exists())
        self.assertFalse(indicadores_para_actividad(date(2027, 1, 1), self.a).exists())

    def test_post_servicio_cross_delegation_y_fuera_periodo_rechazados(self):
        with self.assertRaises(ValidationError):
            self.asociar(self.indicador_b)
        self.actividad.fecha = date(2025, 12, 31)
        aporte = AporteIndicador(actividad=self.actividad, indicador=self.indicador_a)
        with self.assertRaises(ValidationError):
            aporte.full_clean()

    def test_indicador_meta_periodo_inactivos_no_se_ofrecen(self):
        for objeto in (self.indicador_a, self.meta_a, self.periodo):
            objeto.activo = False
            objeto.save()
            self.assertNotIn(self.indicador_a, indicadores_para_actividad(self.actividad.fecha, self.a))
            objeto.activo = True
            objeto.save()

    def test_aporte_personalizado_obligatorio_y_cero_valido(self):
        with self.assertRaises(ValidationError):
            self.asociar(self.otro_indicador, None)
        aporte = self.asociar(self.otro_indicador, Decimal('0'))
        self.assertEqual(aporte.valor_declarado, Decimal('0'))

    def test_asociacion_tardia_bloqueada(self):
        with patch('sgr.plazos.timezone.localdate', return_value=date(2026, 10, 29)):
            with self.assertRaises(PermissionDenied):
                self.asociar()
        self.assertFalse(AporteIndicador.objects.exists())

    def test_cambio_dentro_y_fuera_del_plazo(self):
        aporte = self.asociar()
        aporte = proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('15'), aporte.version)
        evento = aporte.historial.get(accion='cambiar_indicador')
        self.assertEqual(evento.indicador_anterior, self.indicador_a)
        self.assertEqual(evento.indicador_nuevo, self.otro_indicador)
        with patch('sgr.plazos.timezone.localdate', return_value=date(2026, 10, 29)):
            with self.assertRaises(PermissionDenied):
                proponer_aporte(self.request(), self.actividad, self.indicador_a, Decimal('15'), aporte.version)

    def test_pendiente_a_cumple_aprueba_valor_sin_comentario(self):
        aporte = self.asociar()
        self.evidencia()
        aporte = self.decidir(aporte)
        self.assertEqual(aporte.estado, AporteIndicador.Estado.CUMPLE)
        self.assertEqual(aporte.valor_declarado, Decimal('20'))
        self.assertEqual(aporte.valor_validado, Decimal('20'))
        self.assertEqual(aporte.validado_por, self.usuarios['verificador'])
        self.assertIsNotNone(aporte.validado_en)

    def test_valor_distinto_requiere_comentario_no_sobrescribe_declarado(self):
        aporte = self.asociar(self.otro_indicador)
        self.evidencia()
        with self.assertRaises(ValidationError):
            self.decidir(aporte, valor_validado=Decimal('15'))
        aporte = self.decidir(aporte, valor_validado=Decimal('15'), comentario='Se acreditaron 15 árboles.')
        self.assertEqual(aporte.valor_declarado, Decimal('20'))
        self.assertEqual(aporte.valor_validado, Decimal('15'))
        self.assertEqual(aporte.historial.first().validado_nuevo, Decimal('15'))

    def test_requiere_correccion_y_no_cumple_comentario_obligatorio(self):
        aporte = self.asociar()
        self.evidencia()
        for estado in (AporteIndicador.Estado.REQUIERE_CORRECCION, AporteIndicador.Estado.NO_CUMPLE):
            with self.subTest(estado=estado), self.assertRaises(ValidationError):
                self.decidir(aporte, estado=estado, corregir_indicador=True, comentario='   ')
        with self.assertRaises(ValidationError):
            self.decidir(aporte, estado=AporteIndicador.Estado.REQUIERE_CORRECCION, comentario='Corrija')

    def test_correccion_fuera_plazo_reenvia_y_conserva_historial(self):
        aporte = self.asociar()
        self.evidencia()
        aporte = self.decidir(aporte, estado=AporteIndicador.Estado.REQUIERE_CORRECCION,
                             comentario='Seleccione árboles y corrija el número.',
                             corregir_indicador=True, corregir_valor=True)
        with patch('sgr.plazos.timezone.localdate', return_value=date(2026, 11, 10)):
            aporte = proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('15'), aporte.version)
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertIsNone(aporte.validado_por)
        self.assertIsNone(aporte.validado_en)
        self.assertEqual(aporte.comentario, '')
        self.assertTrue(aporte.historial.filter(estado_nuevo=AporteIndicador.Estado.REQUIERE_CORRECCION,
                                              comentario__contains='árboles').exists())
        self.assertTrue(aporte.historial.filter(accion='corregir_aporte', indicador_anterior=self.indicador_a,
                                              indicador_nuevo=self.otro_indicador).exists())

    def test_correccion_solo_campos_autorizados(self):
        aporte = self.asociar()
        self.evidencia()
        aporte = self.decidir(aporte, estado=AporteIndicador.Estado.REQUIERE_CORRECCION,
                             comentario='Corrija solo el valor.', corregir_valor=True)
        with self.assertRaises(ValidationError):
            proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('15'), aporte.version)
        with self.assertRaises(ValidationError):
            proponer_aporte(self.request(), self.actividad, self.indicador_a, Decimal('20'), aporte.version)
        aporte = proponer_aporte(self.request(), self.actividad, self.indicador_a, Decimal('15'), aporte.version)
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)

    def test_no_cumple_y_cumple_no_desbloquean_cambio_libre(self):
        aporte = self.asociar()
        self.evidencia()
        aporte = self.decidir(aporte, estado=AporteIndicador.Estado.NO_CUMPLE, comentario='No corresponde al objetivo.')
        with self.assertRaises(PermissionDenied):
            proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('15'), aporte.version)
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, AtencionCiudadana.Estado.CERRADA)
        self.assertEqual(self.actividad.evidencias.first().estado, Evidencia.Estado.APROBADA)

    def test_cumple_protegido_y_doble_validacion_obsoleta_rechazada(self):
        aporte = self.asociar()
        self.evidencia()
        version = aporte.version
        aporte = self.decidir(aporte)
        with self.assertRaises(PermissionDenied):
            proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('15'), aporte.version)
        with self.assertRaises(ValidationError):
            validar_aporte(self.request('verificador_dos'), aporte.pk, version,
                          AporteIndicador.Estado.NO_CUMPLE, comentario='Otra decisión')
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.CUMPLE)
        self.assertEqual(aporte.validado_por, self.usuarios['verificador'])

    def test_version_anterior_rechazada_tras_correccion_y_reenvio(self):
        aporte = self.asociar()
        self.evidencia()
        version = aporte.version
        aporte = self.decidir(aporte, estado=AporteIndicador.Estado.REQUIERE_CORRECCION,
                             comentario='Corrija el valor', corregir_valor=True)
        aporte = proponer_aporte(self.request(), self.actividad, self.indicador_a, Decimal('15'), aporte.version)
        with self.assertRaises(ValidationError):
            validar_aporte(self.request('verificador_dos'), aporte.pk, version, AporteIndicador.Estado.CUMPLE)


class AportePermisosTests(DatosAportesMixin, TestCase):
    def test_sin_pendiente_rechazada_o_aprobada_no_valida(self):
        aporte = self.asociar()
        for estado in (None, Evidencia.Estado.PENDIENTE, Evidencia.Estado.RECHAZADA):
            if estado:
                self.evidencia(estado)
            with self.subTest(estado=estado), self.assertRaises(ValidationError):
                self.decidir(aporte)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)

    def test_una_aprobada_entre_varias_es_suficiente(self):
        aporte = self.asociar()
        for estado in Evidencia.Estado.values:
            self.evidencia(estado)
        self.assertEqual(self.decidir(aporte).estado, AporteIndicador.Estado.CUMPLE)

    def test_actividad_abierta_con_evidencia_permite_revision_inicial(self):
        aporte = self.asociar()
        self.evidencia()
        self.actividad.estado = AtencionCiudadana.Estado.EN_PROCESO
        self.actividad.save()
        self.assertEqual(self.decidir(aporte).estado, AporteIndicador.Estado.CUMPLE)

    def test_funcionario_y_coordinador_no_validan(self):
        aporte = self.asociar()
        self.evidencia()
        for rol in ('funcionario', 'coordinador'):
            with self.subTest(rol=rol), self.assertRaises(PermissionDenied):
                self.decidir(aporte, rol=rol)

    def test_admin_delegado_y_verificador_validan_sin_autovalidacion(self):
        aporte = self.asociar()
        self.evidencia()
        for rol in ('administrador', 'delegado', 'verificador'):
            self.actividad.creado_por = self.usuarios[rol]
            self.actividad.save()
            with self.subTest(rol=rol), self.assertRaises(PermissionDenied):
                self.decidir(aporte, rol=rol)
        self.actividad.creado_por = self.usuarios['funcionario']
        self.actividad.save()
        self.assertEqual(self.decidir(aporte, rol='delegado').validado_por, self.usuarios['delegado'])

    def test_creador_real_no_responsable_ni_subidor_define_autovalidacion(self):
        aporte = self.asociar()
        self.evidencia()
        self.actividad.responsable = self.usuarios['verificador']
        self.actividad.save()
        self.assertEqual(self.decidir(aporte).estado, AporteIndicador.Estado.CUMPLE)

    def test_alcance_territorial_admin_global_y_sin_alcance(self):
        aporte = self.asociar()
        self.evidencia()
        for rol in ('delegado', 'verificador'):
            request = self.request(rol)
            request.session['delegacion_activa_id'] = self.b.pk
            request.user.perfil.delegaciones.set([self.b])
            request.user.perfil.delegacion = self.b
            request.user.perfil.save()
            with self.subTest(rol=rol), self.assertRaises(PermissionDenied):
                validar_aporte(request, aporte.pk, aporte.version, AporteIndicador.Estado.CUMPLE)
        self.assertEqual(self.decidir(aporte, rol='administrador').estado, AporteIndicador.Estado.CUMPLE)

    def test_multiples_verificadores_ven_pendiente_primero_gana(self):
        aporte = self.asociar()
        self.evidencia()
        for rol in ('verificador', 'verificador_dos'):
            self.assertIn(aporte, pendientes_validacion(self.request(rol)))
        self.decidir(aporte, rol='verificador_dos')
        for rol in ('verificador', 'verificador_dos'):
            self.assertFalse(pendientes_validacion(self.request(rol)).exists())

    def test_bandeja_excluye_propias_no_cerradas_y_sin_evidencia(self):
        aporte = self.asociar()
        self.assertFalse(pendientes_validacion(self.request('verificador')).exists())
        self.evidencia()
        self.actividad.creado_por = self.usuarios['verificador']
        self.actividad.save()
        self.assertFalse(pendientes_validacion(self.request('verificador')).exists())
        self.assertIn(aporte, pendientes_validacion(self.request('verificador_dos')))


class AporteIntegracionTests(DatosAportesMixin, TestCase):
    def test_bandeja_y_post_validacion_sin_csrf_o_rol_denegados(self):
        aporte = self.asociar()
        self.evidencia()
        url = reverse('sgr:aporte_validar', args=[aporte.pk])
        for rol in ('funcionario', 'coordinador'):
            self.entrar(rol)
            self.assertEqual(self.client.get(reverse('sgr:aportes_pendientes')).status_code, 403)
            self.assertEqual(self.client.post(url, {'estado': 'cumple', 'version': aporte.version}).status_code, 403)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['verificador'])
        self.assertEqual(cliente.post(url, {'estado': 'cumple', 'version': aporte.version}).status_code, 403)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)

    def test_autovalidacion_por_url_denegada_y_bandeja_sin_alcance_vacia(self):
        aporte = self.asociar()
        self.evidencia()
        self.actividad.creado_por = self.usuarios['verificador']
        self.actividad.save()
        self.entrar('verificador')
        self.assertEqual(self.client.get(reverse('sgr:aporte_validar', args=[aporte.pk])).status_code, 403)
        self.usuarios['verificador'].perfil.delegaciones.clear()
        respuesta = self.client.get(reverse('sgr:aportes_pendientes'))
        self.assertFalse(respuesta.context['aportes'])

    def test_actividad_sin_indicador_y_sin_periodo_permitida(self):
        self.entrar('funcionario')
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos_actividad(fecha='2025-01-01'))
        self.assertEqual(respuesta.status_code, 302)
        creada = AtencionCiudadana.objects.get(titulo='Actividad nueva')
        self.assertFalse(AporteIndicador.objects.filter(actividad=creada).exists())
        self.assertContains(self.client.get(reverse('atenciones:detalle', args=[creada.pk])), 'Sin Indicador asociado')

    def test_crear_actividad_con_indicador_opcional(self):
        self.entrar('funcionario')
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos_actividad(
            indicador=self.otro_indicador.pk, valor_declarado='20'))
        self.assertEqual(respuesta.status_code, 302)
        aporte = AporteIndicador.objects.get(actividad__titulo='Actividad nueva')
        self.assertEqual(aporte.indicador, self.otro_indicador)
        self.assertEqual(aporte.valor_declarado, Decimal('20'))

    def test_creacion_post_manipulado_y_tardio_rechazados(self):
        self.entrar('funcionario')
        for datos in (self.datos_actividad(indicador=self.indicador_b.pk),
                      self.datos_actividad(fecha='2025-01-01', indicador=self.indicador_a.pk),
                      self.datos_actividad(fecha='2026-10-01', indicador=self.indicador_a.pk)):
            respuesta = self.client.post(reverse('atenciones:crear'), datos)
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('indicador', respuesta.context['form'].errors)
        self.assertFalse(AtencionCiudadana.objects.filter(titulo='Actividad nueva').exists())

    def test_opciones_dinamicas_filtran_fecha_delegacion(self):
        self.entrar('funcionario')
        url = reverse('sgr:indicadores_actividad')
        respuesta = self.client.get(url, {'fecha': '2026-10-23'})
        ids = {i['id'] for i in respuesta.json()['indicadores']}
        self.assertIn(self.indicador_a.pk, ids)
        self.assertNotIn(self.indicador_b.pk, ids)
        self.assertEqual(self.client.get(url, {'fecha': '2025-01-01'}).json()['indicadores'], [])

    def test_propuesta_posterior_csrf_get_y_validacion(self):
        self.entrar('funcionario')
        self.assertEqual(self.client.get(self.url_aporte()).status_code, 200)
        self.assertFalse(AporteIndicador.objects.exists())
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['funcionario'])
        self.assertEqual(cliente.post(self.url_aporte(), {'indicador': self.indicador_a.pk, 'version': 0}).status_code, 403)
        respuesta = self.client.post(self.url_aporte(), {'indicador': self.indicador_a.pk,
                                                       'valor_declarado': '20', 'version': 0})
        self.assertEqual(respuesta.status_code, 302)
        aporte = AporteIndicador.objects.get(actividad=self.actividad)
        self.evidencia()
        self.entrar('verificador')
        url = reverse('sgr:aporte_validar', args=[aporte.pk])
        respuesta = self.client.get(url)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertEqual(self.client.post(url, {'estado': 'cumple', 'version': aporte.version}).status_code, 302)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.CUMPLE)

    def test_post_sin_version_y_comentario_rechazado(self):
        aporte = self.asociar()
        self.evidencia()
        self.entrar('verificador')
        url = reverse('sgr:aporte_validar', args=[aporte.pk])
        for datos in ({'estado': 'cumple'}, {'estado': 'no_cumple', 'version': aporte.version}):
            respuesta = self.client.post(url, datos)
            self.assertEqual(respuesta.status_code, 200)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)

    def test_url_otra_delegacion_y_no_responsable_no_proponen(self):
        self.entrar('coordinador')
        self.assertEqual(self.client.get(self.url_aporte()).status_code, 403)
        self.asociar()
        usuario = self.usuarios['verificador']
        usuario.perfil.delegaciones.set([self.b])
        Perfil.objects.filter(usuario=usuario).update(delegacion=self.b)
        self.entrar('verificador')
        aporte = AporteIndicador.objects.get(actividad=self.actividad)
        self.assertEqual(self.client.get(reverse('sgr:aporte_validar', args=[aporte.pk])).status_code, 404)

    def test_reapertura_reinicia_y_requiere_cierre_sin_borrar_historial(self):
        aporte = self.asociar()
        self.evidencia()
        aporte = self.decidir(aporte)
        self.entrar('delegado')
        url = reverse('atenciones:cambiar_estado', args=[self.actividad.pk])
        self.assertEqual(self.client.post(url, {'estado': 'en_proceso'}).status_code, 302)
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertTrue(aporte.espera_cierre)
        self.assertIsNone(aporte.valor_validado)
        self.assertIsNone(aporte.validado_por)
        self.assertTrue(aporte.historial.filter(estado_nuevo=AporteIndicador.Estado.CUMPLE).exists())
        self.assertTrue(aporte.historial.filter(accion='reiniciar_aporte_reapertura').exists())
        with self.assertRaises(ValidationError):
            self.decidir(aporte)
        self.assertEqual(self.client.post(url, {'estado': 'cerrada'}).status_code, 302)
        aporte = self.decidir(aporte, rol='verificador_dos')
        self.assertEqual(aporte.estado, AporteIndicador.Estado.CUMPLE)
        self.assertEqual(aporte.historial.filter(accion='validar_aporte').count(), 2)

    def test_auditoria_historial_actividad_y_territorialidad(self):
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte)
        self.assertTrue(RegistroAuditoria.objects.filter(modelo='sgr.AporteIndicador', accion='asociar_indicador').exists())
        self.entrar('delegado')
        respuesta = self.client.get(reverse('auditoria:lista'), {'modulo': 'sgr'})
        self.assertEqual(len(respuesta.context['registros']), 3)
        detalle = self.client.get(reverse('atenciones:detalle', args=[self.actividad.pk]))
        self.assertContains(detalle, 'Historial del aporte')
        self.assertContains(detalle, 'Aporte: cumple')
        usuario = self.usuarios['coordinador']
        usuario.perfil.delegaciones.set([self.b])
        Perfil.objects.filter(usuario=usuario).update(delegacion=self.b)
        self.entrar('coordinador')
        self.assertFalse(self.client.get(reverse('auditoria:lista')).context['registros'])


class ProteccionAportesTests(DatosAportesMixin, TestCase):
    def test_objetivo_no_registra_historial_si_no_se_guarda_el_campo(self):
        self.asociar()
        self.indicador_a.valor_objetivo = Decimal('95')
        self.indicador_a._motivo_objetivo = 'Nuevo objetivo'
        self.indicador_a._actor_objetivo = self.usuarios['delegado']
        with self.assertRaises(ValidationError):
            self.indicador_a.save(update_fields=['nombre'])
        self.assertFalse(HistorialObjetivoIndicador.objects.exists())
        self.indicador_a.refresh_from_db()
        self.assertEqual(self.indicador_a.valor_objetivo, Decimal('90'))

    def test_no_desactivar_estructuras_con_aportes_vigentes(self):
        self.asociar()
        for objeto in (self.periodo, self.meta_a, self.indicador_a):
            objeto.activo = False
            with self.subTest(objeto=type(objeto).__name__), self.assertRaises(ValidationError):
                objeto.save()
            objeto.refresh_from_db()
            self.assertTrue(objeto.activo)

    def test_reducir_periodo_invalido_ampliar_y_nombre_seguro(self):
        self.asociar()
        self.periodo.fecha_fin = date(2026, 10, 22)
        with self.assertRaises(ValidationError):
            self.periodo.save()
        self.periodo.refresh_from_db()
        self.periodo.fecha_inicio = date(2025, 12, 1)
        self.periodo.nombre = 'Nombre seguro'
        self.periodo.save()
        for objeto in (self.meta_a, self.indicador_a):
            objeto.nombre = f'{objeto.nombre} actualizado'
            objeto.save()

    def test_cambio_objetivo_exige_motivo_y_actor_conserva_historial(self):
        self.asociar()
        self.indicador_a.valor_objetivo = Decimal('95')
        with self.assertRaises(ValidationError):
            self.indicador_a.save()
        self.indicador_a._motivo_objetivo = 'Nueva planificación'
        with self.assertRaises(ValidationError):
            self.indicador_a.save()
        self.indicador_a._actor_objetivo = self.usuarios['delegado']
        self.indicador_a._request_objetivo = self.request('delegado')
        self.indicador_a.save()
        historial = HistorialObjetivoIndicador.objects.get(indicador=self.indicador_a)
        self.assertEqual(historial.valor_anterior, Decimal('90'))
        self.assertEqual(historial.valor_nuevo, Decimal('95'))
        self.assertEqual(historial.usuario, self.usuarios['delegado'])
        self.assertEqual(historial.motivo, 'Nueva planificación')
        self.assertTrue(RegistroAuditoria.objects.filter(accion='cambiar_objetivo_indicador').exists())

    def test_formulario_objetivo_con_aportes_y_motivo(self):
        self.asociar()
        self.entrar('delegado')
        url = reverse('sgr:indicador_editar', args=[self.indicador_a.pk])
        datos = dict(nombre=self.indicador_a.nombre, descripcion='', unidad_medida='porcentaje',
                     sentido='mayor', valor_objetivo='95')
        respuesta = self.client.post(url, datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context['form'].errors)
        datos['motivo_objetivo'] = 'Revisión de planificación'
        self.assertEqual(self.client.post(url, datos).status_code, 302)
        self.assertEqual(HistorialObjetivoIndicador.objects.count(), 1)

    def test_indicador_anterior_conserva_proteccion_y_trazabilidad_objetivo(self):
        aporte = self.asociar()
        proponer_aporte(self.request(), self.actividad, self.otro_indicador, Decimal('20'), aporte.version)
        self.assertTrue(self.indicador_a.tiene_vinculaciones)
        self.indicador_a.valor_objetivo = Decimal('95')
        with self.assertRaises(ValidationError):
            self.indicador_a.save()
        self.assertTrue(EventoAporte.objects.filter(indicador_anterior=self.indicador_a).exists())
