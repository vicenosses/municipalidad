from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from evidencias.models import Evidencia
from sgr.aportes import proponer_aporte
from sgr.calculos import calcular_avance_actividad, calcular_avance_indicador
from sgr.models import AporteIndicador, EventoAporte, Indicador
from sgr.test_aportes import DatosAportesMixin
from usuarios.models import Perfil


class DatosAvanceMixin(DatosAportesMixin):
    def vincular(self, estado_actividad=AtencionCiudadana.Estado.REGISTRADA,
                 estado_aporte=AporteIndicador.Estado.PENDIENTE, evidencias=(), indicador=None):
        indicador = indicador or self.indicador_a
        actividad = AtencionCiudadana.objects.create(
            titulo='Actividad de avance', fecha=self.actividad.fecha, solicitante='Solicitante',
            tipo=self.tipo, subatencion=self.sub, descripcion='Actividad considerada',
            delegacion=indicador.meta.delegacion, responsable=self.usuarios['funcionario'],
            creado_por=self.usuarios['funcionario'], estado=estado_actividad,
        )
        aporte = AporteIndicador.objects.create(
            actividad=actividad, indicador=indicador, estado=estado_aporte,
            valor_declarado=Decimal('20'),
            valor_validado=Decimal('20') if estado_aporte == AporteIndicador.Estado.CUMPLE else None,
            comentario='Decisión de prueba' if estado_aporte != AporteIndicador.Estado.PENDIENTE else '',
            corregir_valor=estado_aporte == AporteIndicador.Estado.REQUIERE_CORRECCION,
            validado_por=self.usuarios['verificador'] if estado_aporte != AporteIndicador.Estado.PENDIENTE else None,
            validado_en=timezone.now() if estado_aporte != AporteIndicador.Estado.PENDIENTE else None,
        )
        for estado in evidencias:
            Evidencia.objects.create(atencion=actividad, estado=estado,
                subido_por=self.usuarios['funcionario'], archivo='avance.jpg')
        return aporte


class PuntajeActividadTests(DatosAvanceMixin, TestCase):
    def puntaje(self, estado, evidencias=()):
        return calcular_avance_actividad(self.vincular(estado, evidencias=evidencias).actividad)

    def test_registrada_cero_incluso_con_evidencia_aprobada(self):
        for evidencias in ((), ('aprobada',)):
            with self.subTest(evidencias=evidencias):
                self.assertEqual(self.puntaje(AtencionCiudadana.Estado.REGISTRADA, evidencias), Decimal('0'))

    def test_en_proceso_cero_incluso_con_evidencia_aprobada(self):
        for evidencias in ((), ('pendiente',), ('rechazada',), ('aprobada',)):
            with self.subTest(evidencias=evidencias):
                self.assertEqual(self.puntaje(AtencionCiudadana.Estado.EN_PROCESO, evidencias), Decimal('0'))

    def test_cerrada_sin_evidencia_cero(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA), Decimal('0'))

    def test_cerrada_solo_pendiente_cero(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('pendiente',)), Decimal('0'))

    def test_cerrada_solo_rechazada_cero(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('rechazada',)), Decimal('0'))

    def test_cerrada_pendientes_y_rechazadas_sin_aprobada_cero(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('pendiente', 'rechazada')), Decimal('0'))

    def test_cerrada_aprobada_uno(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('aprobada',)), Decimal('1'))

    def test_cerrada_aprobada_y_rechazada_uno(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('aprobada', 'rechazada')), Decimal('1'))

    def test_cerrada_aprobada_y_pendiente_uno(self):
        self.assertEqual(self.puntaje(AtencionCiudadana.Estado.CERRADA, ('aprobada', 'pendiente')), Decimal('1'))

    def test_sin_penalizacion_por_fecha_antigua(self):
        aporte = self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',))
        aporte.actividad.fecha = self.actividad.fecha.replace(year=2020)
        self.assertEqual(calcular_avance_actividad(aporte.actividad), Decimal('1'))

    def test_tabla_completa_solo_devuelve_decimales_binarios(self):
        for estado in AtencionCiudadana.Estado.values:
            for aprobada in (False, True):
                with self.subTest(estado=estado, aprobada=aprobada):
                    actividad = AtencionCiudadana(estado=estado)
                    with self.assertNumQueries(0):
                        valor = calcular_avance_actividad(actividad, evidencia_aprobada=aprobada)
                    esperado = Decimal('1') if estado == 'cerrada' and aprobada else Decimal('0')
                    self.assertIsInstance(valor, Decimal)
                    self.assertEqual(valor, esperado)
                    self.assertIn(valor, (Decimal('0'), Decimal('1')))

    def test_evidencia_de_otra_actividad_no_cuenta(self):
        self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',))
        aporte = self.vincular(AtencionCiudadana.Estado.CERRADA)
        self.assertEqual(calcular_avance_actividad(aporte.actividad), Decimal('0'))

    def test_evidencia_de_agenda_no_respalda_actividad_sin_guardar_ni_existente(self):
        compromiso = Compromiso.objects.create(titulo='Respaldo de Agenda', fecha_hora=timezone.now(),
            delegacion=self.a, responsable=self.usuarios['funcionario'])
        Evidencia.objects.create(compromiso=compromiso, estado=Evidencia.Estado.APROBADA,
            subido_por=self.usuarios['funcionario'], archivo='agenda.jpg')
        sin_guardar = AtencionCiudadana(estado=AtencionCiudadana.Estado.CERRADA)
        with self.assertNumQueries(0):
            self.assertEqual(calcular_avance_actividad(sin_guardar), Decimal('0'))
        self.assertEqual(calcular_avance_actividad(self.actividad), Decimal('0'))


class AvanceIndicadorTests(DatosAvanceMixin, TestCase):
    def calcular(self):
        return calcular_avance_indicador(self.indicador_a)

    def test_pendiente_y_cumple_entran_en_denominador(self):
        for estado in (AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.CUMPLE):
            self.vincular(AtencionCiudadana.Estado.EN_PROCESO, estado, evidencias=('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 2)
        self.assertEqual(avance.cantidad_pendientes, 1)
        self.assertEqual(avance.cantidad_cumple, 1)
        self.assertEqual(avance.puntos_ponderados, Decimal('0'))
        self.assertEqual(avance.porcentaje_avance, Decimal('0.00'))
        self.assertEqual(avance.no_completas, 2)

    def test_no_cumple_se_excluye_del_denominador_no_es_un_cero(self):
        self.vincular(AtencionCiudadana.Estado.CERRADA, AporteIndicador.Estado.NO_CUMPLE, ('aprobada',))
        self.vincular()
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 2)
        self.assertEqual(avance.cantidad_consideradas, 1)
        self.assertEqual(avance.excluidas_no_cumple, 1)
        self.assertEqual(avance.sin_avance, 1)
        self.assertEqual(avance.puntos_ponderados, Decimal('0'))
        self.assertEqual(avance.porcentaje_avance, Decimal('0.00'))

    def test_correccion_temporalmente_excluida(self):
        self.vincular(AtencionCiudadana.Estado.CERRADA, AporteIndicador.Estado.REQUIERE_CORRECCION, ('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 0)
        self.assertEqual(avance.excluidas_correccion, 1)
        self.assertFalse(avance.hay_base_calculable)
        self.assertIsNone(avance.porcentaje_avance)

    def test_ejemplo_b_seis_completas_y_no_cumple_excluido_66_67(self):
        for _ in range(6):
            self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',))
        for _ in range(2):
            self.vincular(AtencionCiudadana.Estado.EN_PROCESO)
        self.vincular()
        self.vincular(AtencionCiudadana.Estado.CERRADA, AporteIndicador.Estado.NO_CUMPLE, ('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 10)
        self.assertEqual(avance.cantidad_consideradas, 9)
        self.assertEqual(avance.puntos_ponderados, Decimal('6'))
        self.assertEqual(avance.porcentaje_avance, Decimal('66.67'))
        self.assertEqual((avance.completas, avance.en_proceso, avance.sin_avance), (6, 2, 3))
        self.assertEqual(avance.no_completas, 3)
        self.assertEqual(avance.cantidad_excluidas, 1)

    def test_ejemplo_c_62_50_y_reenvio_real_devuelve_actividad_al_denominador(self):
        for _ in range(5):
            self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',))
        for _ in range(2):
            self.vincular(AtencionCiudadana.Estado.EN_PROCESO)
        self.vincular()
        correccion = self.vincular(AtencionCiudadana.Estado.CERRADA,
                                   AporteIndicador.Estado.REQUIERE_CORRECCION, ('aprobada',))
        self.vincular(AtencionCiudadana.Estado.CERRADA, AporteIndicador.Estado.NO_CUMPLE, ('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 10)
        self.assertEqual(avance.cantidad_consideradas, 8)
        self.assertEqual(avance.puntos_ponderados, Decimal('5'))
        self.assertEqual(avance.porcentaje_avance, Decimal('62.50'))
        self.assertEqual((avance.completas, avance.no_completas), (5, 3))
        self.assertEqual(avance.cantidad_excluidas, 2)
        proponer_aporte(self.request(), correccion.actividad, self.indicador_a, Decimal('15'), correccion.version)
        nuevo = self.calcular()
        self.assertEqual(nuevo.cantidad_consideradas, 9)
        self.assertEqual(nuevo.puntos_ponderados, Decimal('6'))
        self.assertEqual(nuevo.porcentaje_avance, Decimal('66.67'))

    def test_ejemplo_a_seis_completas_dos_en_proceso_dos_registradas_60(self):
        for _ in range(6):
            self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',))
        for _ in range(2):
            self.vincular(AtencionCiudadana.Estado.EN_PROCESO, evidencias=('aprobada',))
            self.vincular(AtencionCiudadana.Estado.REGISTRADA)
        avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 10)
        self.assertEqual((avance.completas, avance.no_completas), (6, 4))
        self.assertEqual(avance.puntos_ponderados, Decimal('6'))
        self.assertEqual(avance.porcentaje_avance, Decimal('60.00'))

    def test_sin_aportes_no_existe_base_calculable(self):
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 0)
        self.assertEqual(avance.cantidad_consideradas, 0)
        self.assertEqual(avance.puntos_ponderados, Decimal('0'))
        self.assertIsNone(avance.porcentaje_avance)
        self.assertFalse(avance.hay_base_calculable)

    def test_todos_excluidos_sin_base_calculable(self):
        for estado in (AporteIndicador.Estado.NO_CUMPLE, AporteIndicador.Estado.REQUIERE_CORRECCION):
            self.vincular(AtencionCiudadana.Estado.CERRADA, estado, ('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 2)
        self.assertEqual(avance.cantidad_excluidas, 2)
        self.assertIsNone(avance.porcentaje_avance)

    def test_registradas_y_en_proceso_son_cero_real_con_base(self):
        for _ in range(3):
            self.vincular()
        for _ in range(2):
            self.vincular(AtencionCiudadana.Estado.EN_PROCESO, evidencias=('aprobada',))
        avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 5)
        self.assertEqual(avance.puntos_ponderados, Decimal('0'))
        self.assertEqual(avance.porcentaje_avance, Decimal('0.00'))
        self.assertTrue(avance.hay_base_calculable)
        self.assertEqual((avance.completas, avance.no_completas), (0, 5))

    def test_pendiente_completo_es_uno_provisional_y_no_cumple_lo_excluye(self):
        aporte = self.asociar()
        self.evidencia()
        avance = self.calcular()
        self.assertEqual(avance.porcentaje_avance, Decimal('100.00'))
        self.assertEqual(avance.cantidad_pendientes, 1)
        self.decidir(aporte, estado=AporteIndicador.Estado.NO_CUMPLE, comentario='No aporta al Indicador.')
        self.assertEqual(self.calcular().cantidad_consideradas, 0)
        self.assertIsNone(self.calcular().porcentaje_avance)

    def test_reapertura_real_cambia_uno_a_cero_y_cierre_devuelve_uno(self):
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte)
        self.assertEqual(self.calcular().puntos_ponderados, Decimal('1'))
        self.entrar('delegado')
        url = reverse('atenciones:cambiar_estado', args=[self.actividad.pk])
        self.assertEqual(self.client.post(url, {'estado': 'en_proceso'}).status_code, 302)
        avance = self.calcular()
        self.assertEqual(avance.puntos_ponderados, Decimal('0'))
        self.assertEqual(avance.porcentaje_avance, Decimal('0.00'))
        self.assertEqual((avance.completas, avance.no_completas), (0, 1))
        aporte.refresh_from_db()
        self.assertTrue(aporte.espera_cierre)
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertTrue(aporte.historial.filter(estado_nuevo=AporteIndicador.Estado.CUMPLE).exists())
        self.assertEqual(self.client.post(url, {'estado': 'cerrada'}).status_code, 302)
        self.assertEqual(self.calcular().puntos_ponderados, Decimal('1'))
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.PENDIENTE)
        self.assertTrue(aporte.espera_cierre)

    def test_evidencia_actual_se_recalcula_sin_congelar_puntos(self):
        self.asociar()
        evidencia = self.evidencia()
        self.assertEqual(self.calcular().puntos_ponderados, Decimal('1'))
        evidencia.estado = Evidencia.Estado.RECHAZADA
        evidencia.save()
        self.assertEqual(self.calcular().puntos_ponderados, Decimal('0'))
        self.assertEqual(self.calcular().cantidad_consideradas, 1)

    def test_varias_evidencias_no_duplican_actividad(self):
        self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada', 'aprobada', 'rechazada'))
        avance = self.calcular()
        self.assertEqual(avance.total_vinculaciones, 1)
        self.assertEqual(avance.cantidad_consideradas, 1)
        self.assertEqual(avance.puntos_ponderados, Decimal('1'))

    def test_formula_independiente_de_unidad_sentido_y_objetivo(self):
        self.vincular(AtencionCiudadana.Estado.EN_PROCESO)
        for unidad in Indicador.Unidad.values:
            for sentido in Indicador.Sentido.values:
                self.indicador_a.unidad_medida = unidad
                self.indicador_a.unidad_personalizada = 'árboles' if unidad == Indicador.Unidad.OTRA else ''
                self.indicador_a.sentido = sentido
                self.indicador_a.save()
                with self.subTest(unidad=unidad, sentido=sentido):
                    self.assertEqual(self.calcular().porcentaje_avance, Decimal('0.00'))
        self.indicador_a.valor_objetivo = Decimal('0')
        self.assertEqual(self.calcular().porcentaje_avance, Decimal('0.00'))

    def test_una_consulta_con_cero_o_muchas_actividades_y_evidencias(self):
        with self.assertNumQueries(1):
            self.calcular()
        for _ in range(20):
            self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada', 'pendiente'))
        with self.assertNumQueries(1):
            avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 20)
        self.assertEqual(avance.puntos_ponderados, Decimal('20'))

    def test_deshabilitada_conserva_asociacion_y_puntaje_segun_estado(self):
        aporte = self.asociar()
        self.evidencia()
        self.entrar('delegado')
        url = reverse('atenciones:cambiar_disponibilidad', args=[self.actividad.pk])
        self.assertEqual(self.client.post(url, {'activo': 'false'}).status_code, 302)
        avance = self.calcular()
        self.assertEqual(avance.cantidad_consideradas, 1)
        self.assertEqual(avance.deshabilitadas, 1)
        self.assertEqual(avance.consideradas_deshabilitadas, 1)
        self.assertEqual(avance.puntos_ponderados, Decimal('1'))
        self.assertEqual(AporteIndicador.objects.get(pk=aporte.pk).historial.count(), 2)


class AvancePresentacionTests(DatosAvanceMixin, TestCase):
    def test_detalle_muestra_resumen_operativo_y_exclusiones(self):
        self.vincular(AtencionCiudadana.Estado.EN_PROCESO)
        self.vincular(estado_aporte=AporteIndicador.Estado.NO_CUMPLE)
        self.entrar('delegado')
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        avance = respuesta.context['avance_actividades']
        self.assertEqual(avance.porcentaje_avance, Decimal('0.00'))
        self.assertContains(respuesta, 'Avance de actividades')
        self.assertContains(respuesta, 'Avance: 0,00%')
        self.assertContains(respuesta, 'Avance operacional binario')
        self.assertContains(respuesta, 'No completas (0)')
        self.assertContains(respuesta, 'En proceso, incluidas en No completas (0)')
        self.assertNotContains(respuesta, '0,5')
        self.assertNotContains(respuesta, 'Puntos ponderados')
        self.assertContains(respuesta, 'no representa aprobación estratégica ni cumplimiento')
        self.assertContains(respuesta, 'Excluidas por No cumple')
        self.assertContains(respuesta, 'Excluidas temporalmente por Requiere corrección')

    def test_ui_distingue_sin_base_y_cero_real(self):
        self.entrar('administrador')
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Sin actividades consideradas')
        self.assertNotContains(respuesta, 'Avance: 0,00%')
        self.vincular()
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Avance: 0,00%')
        self.assertNotContains(respuesta, 'Sin actividades consideradas')

    def test_solo_alcances_existentes_pueden_ver_el_calculo(self):
        self.vincular(AtencionCiudadana.Estado.CERRADA, evidencias=('aprobada',), indicador=self.indicador_b)
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.indicador_b.get_absolute_url())
            self.assertEqual(respuesta.status_code, 404)
            self.assertNotContains(respuesta, 'Avance de actividades', status_code=404)
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            self.assertEqual(self.client.get(self.indicador_a.get_absolute_url()).status_code, 403)
        self.entrar('administrador')
        respuesta = self.client.get(self.indicador_b.get_absolute_url())
        self.assertEqual(respuesta.context['avance_actividades'].puntos_ponderados, Decimal('1'))

    def test_territorial_sin_delegacion_autorizada_no_accede(self):
        usuario = self.usuarios['coordinador']
        usuario.perfil.delegaciones.clear()
        Perfil.objects.filter(usuario=usuario).update(delegacion=None)
        self.entrar('coordinador')
        self.assertEqual(self.client.get(self.indicador_a.get_absolute_url()).status_code, 404)

    def test_calcular_y_abrir_detalle_no_escribe_auditoria_ni_historial(self):
        aporte = self.asociar()
        self.evidencia()
        auditorias = RegistroAuditoria.objects.count()
        eventos = EventoAporte.objects.count()
        datos = AporteIndicador.objects.filter(pk=aporte.pk).values().get()
        self.entrar('delegado')
        for _ in range(2):
            calcular_avance_indicador(self.indicador_a)
            self.assertEqual(self.client.get(self.indicador_a.get_absolute_url()).status_code, 200)
        self.assertEqual(RegistroAuditoria.objects.count(), auditorias)
        self.assertEqual(EventoAporte.objects.count(), eventos)
        self.assertEqual(AporteIndicador.objects.filter(pk=aporte.pk).values().get(), datos)

    def test_ui_identifica_deshabilitadas_sin_excluirlas_silenciosamente(self):
        aporte = self.vincular(AtencionCiudadana.Estado.EN_PROCESO)
        aporte.actividad.activo = False
        aporte.actividad.save()
        self.entrar('delegado')
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Actividades vinculadas deshabilitadas')
        self.assertEqual(respuesta.context['avance_actividades'].cantidad_consideradas, 1)
        self.assertEqual(respuesta.context['avance_actividades'].porcentaje_avance, Decimal('0.00'))
