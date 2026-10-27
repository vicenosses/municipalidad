from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from atenciones.estados import cambiar_estado_actividad
from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from auditoria.models import RegistroAuditoria
from sgr.calculos import (
    EstadoCumplimiento, calcular_avance_indicador, calcular_cumplimiento, calcular_resultado_indicador,
)
from sgr.models import AporteIndicador, HistorialObjetivoIndicador, Indicador
from sgr.test_calculos import DatosAvanceMixin
from sgr.tiempos import calcular_duracion_actividad, microsegundos_habiles, MICROSEGUNDOS_DIA


class DatosMetricasMixin(DatosAvanceMixin):
    def configurar(self, unidad=Indicador.Unidad.CANTIDAD, objetivo='10', sentido=Indicador.Sentido.MAYOR):
        self.indicador_a.unidad_medida = unidad
        self.indicador_a.unidad_personalizada = 'árboles' if unidad == Indicador.Unidad.OTRA else ''
        self.indicador_a.sentido = sentido
        self.indicador_a.valor_objetivo = Decimal(objetivo)
        self.indicador_a.save()
        return self.indicador_a

    def calcular(self):
        return calcular_resultado_indicador(self.indicador_a)

    def instante(self, dia, hora, minuto=0):
        return datetime(2026, 10, dia, hora, minuto, tzinfo=timezone.get_default_timezone())

    def ciclos(self, pares, estado_aporte=AporteIndicador.Estado.CUMPLE):
        aporte = self.vincular(AtencionCiudadana.Estado.CERRADA, estado_aporte, ('aprobada',))
        actividad = aporte.actividad
        registro = pares[0][0] - timedelta(hours=1)
        AtencionCiudadana.objects.filter(pk=actividad.pk).update(fecha_registro=registro)
        HistorialEstadoActividad.objects.create(actividad=actividad, estado_nuevo='registrada',
            actor=self.usuarios['funcionario'], fecha_hora=registro)
        for posicion, (inicio, fin) in enumerate(pares):
            HistorialEstadoActividad.objects.create(actividad=actividad,
                estado_anterior='registrada' if posicion == 0 else 'cerrada', estado_nuevo='en_proceso',
                actor=self.usuarios['funcionario'], fecha_hora=inicio)
            if fin is not None:
                HistorialEstadoActividad.objects.create(actividad=actividad, estado_anterior='en_proceso',
                    estado_nuevo='cerrada', actor=self.usuarios['funcionario'], fecha_hora=fin)
        if pares[-1][1] is None:
            actividad.estado = AtencionCiudadana.Estado.EN_PROCESO
            actividad.save(update_fields=['estado'])
        return aporte

    def duracion(self, aporte, dias=False):
        return calcular_duracion_actividad(aporte.actividad,
            aporte.actividad.historial_estados.order_by('pk'), dias_habiles=dias)


class CumplimientoTests(TestCase):
    def test_mayor_es_mejor_y_sobrecumplimiento_sin_tope(self):
        for resultado, objetivo, esperado in (('8', '10', '80.00'), ('15', '10', '150.00'),
                                             ('20', '10', '200.00'), ('125', '100', '125.00')):
            valor = calcular_cumplimiento(Decimal(resultado), Decimal(objetivo), Indicador.Sentido.MAYOR)
            self.assertEqual(valor.porcentaje, Decimal(esperado))
            self.assertEqual(valor.estado, EstadoCumplimiento.CALCULADO)

    def test_menor_es_mejor(self):
        for resultado, esperado in (('20', '120.00'), ('30', '80.00')):
            valor = calcular_cumplimiento(Decimal(resultado), Decimal('24'), Indicador.Sentido.MENOR)
            self.assertEqual(valor.porcentaje, Decimal(esperado))

    def test_resultado_cero_mayor_es_cero_real(self):
        valor = calcular_cumplimiento(Decimal('0'), Decimal('10'), Indicador.Sentido.MAYOR)
        self.assertEqual(valor.porcentaje, Decimal('0.00'))

    def test_resultado_cero_menor_es_estado_sin_limite_sin_infinito(self):
        valor = calcular_cumplimiento(Decimal('0'), Decimal('10'), Indicador.Sentido.MENOR)
        self.assertIsNone(valor.porcentaje)
        self.assertEqual(valor.estado, EstadoCumplimiento.SIN_LIMITE)

    def test_objetivo_cero_negativo_y_no_finito_no_dividen(self):
        for objetivo in ('0', '-1', 'NaN', 'Infinity'):
            for sentido in Indicador.Sentido.values:
                valor = calcular_cumplimiento(Decimal('5'), Decimal(objetivo), sentido)
                self.assertIsNone(valor.porcentaje)
                self.assertEqual(valor.estado, EstadoCumplimiento.OBJETIVO_INVALIDO)

    def test_resultado_none_no_se_convierte_a_cero(self):
        valor = calcular_cumplimiento(None, Decimal('10'), Indicador.Sentido.MAYOR)
        self.assertIsNone(valor.porcentaje)
        self.assertEqual(valor.estado, EstadoCumplimiento.SIN_RESULTADO)

    def test_resultado_invalido_no_genera_nan_o_infinity(self):
        for resultado in ('NaN', 'Infinity', '-1'):
            valor = calcular_cumplimiento(Decimal(resultado), Decimal('10'), Indicador.Sentido.MAYOR)
            self.assertIsNone(valor.porcentaje)
            self.assertEqual(valor.estado, EstadoCumplimiento.DATOS_INVALIDOS)

    def test_precision_y_redondeo_decimal(self):
        valor = calcular_cumplimiento(Decimal('7'), Decimal('9'), Indicador.Sentido.MAYOR)
        self.assertEqual(valor.porcentaje, Decimal('77.78'))
        valor = calcular_cumplimiento(Decimal('0.00000000000000001'), Decimal('9999999999.99'),
                                      Indicador.Sentido.MENOR)
        self.assertTrue(valor.porcentaje.is_finite())


class ResultadoNumericoTests(DatosMetricasMixin, TestCase):
    def test_cantidad_solo_cumple_suma(self):
        self.configurar()
        for _ in range(8):
            self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        for estado in (AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.REQUIERE_CORRECCION,
                       AporteIndicador.Estado.NO_CUMPLE):
            self.vincular(estado_aporte=estado)
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('8'))
        self.assertEqual(valor.base_utilizada, 8)
        self.assertEqual(valor.cumplimiento.porcentaje, Decimal('80.00'))

    def test_cantidad_supera_objetivo_y_100_por_ciento(self):
        self.configurar(objetivo='2')
        for _ in range(3):
            self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        self.assertEqual(self.calcular().resultado, Decimal('3'))
        self.assertEqual(self.calcular().cumplimiento.porcentaje, Decimal('150.00'))

    def test_cantidad_sin_aportes_es_cero_y_menor_cero_es_especial(self):
        self.configurar(sentido=Indicador.Sentido.MENOR)
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('0'))
        self.assertEqual(valor.base_utilizada, 0)
        self.assertEqual(valor.cumplimiento.estado, EstadoCumplimiento.SIN_LIMITE)

    def test_porcentaje_70_y_cumplimiento_87_50(self):
        self.configurar(Indicador.Unidad.PORCENTAJE, '80')
        for _ in range(7):
            self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        for _ in range(3):
            self.vincular(estado_aporte=AporteIndicador.Estado.NO_CUMPLE)
        for _ in range(2):
            self.vincular()
        self.vincular(estado_aporte=AporteIndicador.Estado.REQUIERE_CORRECCION)
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('70'))
        self.assertEqual(valor.base_utilizada, 10)
        self.assertEqual(valor.cantidad_pendiente, 2)
        self.assertEqual(valor.cantidad_correccion, 1)
        self.assertEqual(valor.cumplimiento.porcentaje, Decimal('87.50'))

    def test_porcentaje_sin_evaluados_es_none(self):
        self.configurar(Indicador.Unidad.PORCENTAJE, '80')
        self.assertIsNone(self.calcular().resultado)
        self.vincular()
        self.vincular(estado_aporte=AporteIndicador.Estado.REQUIERE_CORRECCION)
        self.assertIsNone(self.calcular().resultado)
        self.assertIsNone(self.calcular().cumplimiento.porcentaje)

    def test_porcentaje_evaluado_sin_cumple_es_cero_real(self):
        self.configurar(Indicador.Unidad.PORCENTAJE, '80')
        self.vincular(estado_aporte=AporteIndicador.Estado.NO_CUMPLE)
        self.assertEqual(self.calcular().resultado, Decimal('0'))
        self.assertEqual(self.calcular().cumplimiento.porcentaje, Decimal('0.00'))

    def test_otra_suma_validados_no_declarados_ni_otros_estados(self):
        self.configurar(Indicador.Unidad.OTRA, '100')
        for validado in (30, 20):
            aporte = self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
            AporteIndicador.objects.filter(pk=aporte.pk).update(valor_declarado=25, valor_validado=validado)
        for estado in (AporteIndicador.Estado.PENDIENTE, AporteIndicador.Estado.REQUIERE_CORRECCION,
                       AporteIndicador.Estado.NO_CUMPLE):
            aporte = self.vincular(estado_aporte=estado)
            AporteIndicador.objects.filter(pk=aporte.pk).update(valor_declarado=40, valor_validado=40)
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('50'))
        self.assertEqual(valor.base_utilizada, 2)
        self.assertEqual(valor.unidad_presentacion, 'árboles')
        self.assertEqual(valor.cumplimiento.porcentaje, Decimal('50.00'))
        self.assertEqual(list(AporteIndicador.objects.filter(estado='cumple').values_list('valor_declarado', flat=True)),
                         [Decimal('25'), Decimal('25')])

    def test_otra_sin_cumple_es_cero_y_valor_validado_cero_es_real(self):
        self.configurar(Indicador.Unidad.OTRA, '100')
        self.assertEqual(self.calcular().resultado, Decimal('0'))
        aporte = self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=0)
        self.assertEqual(self.calcular().resultado, Decimal('0'))
        self.assertEqual(self.calcular().base_utilizada, 1)

    def test_otra_sin_valor_validado_no_inventa_declarado(self):
        self.configurar(Indicador.Unidad.OTRA, '100')
        aporte = self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=None)
        valor = self.calcular()
        self.assertIsNone(valor.resultado)
        self.assertEqual(valor.sin_valor_validado, 1)
        self.assertTrue(valor.observaciones)

    def test_objetivo_actual_recalcula_y_conserva_historial(self):
        self.configurar(Indicador.Unidad.OTRA, '100')
        aporte = self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=50)
        self.assertEqual(self.calcular().cumplimiento.porcentaje, Decimal('50.00'))
        actualizado = Indicador.objects.get(pk=self.indicador_a.pk)
        actualizado.valor_objetivo = Decimal('80')
        actualizado._motivo_objetivo = 'Revisión de planificación'
        actualizado._actor_objetivo = self.usuarios['delegado']
        actualizado._request_objetivo = self.request('delegado')
        actualizado.save()
        valor = self.calcular()  # Se pasa la instancia antigua: debe usar el dato vigente.
        self.assertEqual(valor.resultado, Decimal('50'))
        self.assertEqual(valor.objetivo, Decimal('80'))
        self.assertEqual(valor.cumplimiento.porcentaje, Decimal('62.50'))
        historial = HistorialObjetivoIndicador.objects.get(indicador=self.indicador_a)
        self.assertEqual((historial.valor_anterior, historial.valor_nuevo), (Decimal('100'), Decimal('80')))

    def test_tres_valores_operacional_metrico_y_cumplimiento_distintos(self):
        self.configurar(Indicador.Unidad.PORCENTAJE, '80')
        for _ in range(5):
            self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, ('aprobada',))
        en_proceso = []
        for _ in range(2):
            en_proceso.append(self.vincular('en_proceso', AporteIndicador.Estado.CUMPLE, ('aprobada',)))
        self.vincular('registrada')
        for _ in range(3):
            self.vincular(estado_aporte=AporteIndicador.Estado.NO_CUMPLE)
        avance = calcular_avance_indicador(self.indicador_a)
        metrica = self.calcular()
        self.assertEqual(avance.porcentaje_avance, Decimal('62.50'))
        self.assertEqual(metrica.resultado, Decimal('70'))
        self.assertEqual(metrica.cumplimiento.porcentaje, Decimal('87.50'))
        cambiar_estado_actividad(self.request(), en_proceso[0].actividad_id, 'cerrada')
        self.assertEqual(calcular_avance_indicador(self.indicador_a).porcentaje_avance, Decimal('75.00'))
        actual = self.calcular()
        self.assertEqual(actual.resultado, metrica.resultado)
        self.assertEqual(actual.cumplimiento, metrica.cumplimiento)

    def test_reapertura_real_retira_cumple_hasta_nueva_validacion(self):
        self.configurar()
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte)
        self.assertEqual(self.calcular().resultado, Decimal('1'))
        cambiar_estado_actividad(self.request('delegado'), self.actividad.pk, 'en_proceso')
        self.assertEqual(self.calcular().resultado, Decimal('0'))
        cambiar_estado_actividad(self.request(), self.actividad.pk, 'cerrada')
        self.assertEqual(self.calcular().resultado, Decimal('0'))
        aporte.refresh_from_db()
        self.decidir(aporte)
        self.assertEqual(self.calcular().resultado, Decimal('1'))


class ResultadoTemporalTests(DatosMetricasMixin, TestCase):
    def test_horas_ciclo_simple_real(self):
        self.configurar(Indicador.Unidad.HORAS, '24', Indicador.Sentido.MENOR)
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        self.assertEqual(self.duracion(aporte).valor, Decimal('5'))
        self.assertEqual(self.calcular().resultado, Decimal('5'))

    def test_horas_reapertura_suma_ciclos_no_intervalo_cerrado(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 12)),
                              (self.instante(26, 14), self.instante(26, 16))])
        duracion = self.duracion(aporte)
        self.assertEqual(duracion.ciclos_completos, 2)
        self.assertEqual(duracion.valor, Decimal('5'))
        self.assertEqual(self.calcular().resultado, Decimal('5'))

    def test_promedio_horas_no_suma_actividades(self):
        self.configurar(Indicador.Unidad.HORAS, '24', Indicador.Sentido.MENOR)
        inicio = self.instante(26, 0)
        for horas in (10, 20, 15):
            self.ciclos([(inicio, inicio + timedelta(hours=horas))])
        valor = self.calcular()
        self.assertEqual(valor.base_utilizada, 3)
        self.assertEqual(valor.resultado, Decimal('15'))
        self.assertEqual(valor.cumplimiento.porcentaje, Decimal('160.00'))

    def test_horas_totales_no_limitadas_a_horario_laboral(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.ciclos([(self.instante(26, 15), self.instante(27, 10))])
        self.assertEqual(self.calcular().resultado, Decimal('19'))

    def test_solo_cumple_participa_en_temporal(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        for estado in AporteIndicador.Estado.values:
            self.ciclos([(self.instante(26, 9), self.instante(26, 14))], estado)
        valor = self.calcular()
        self.assertEqual(valor.base_utilizada, 1)
        self.assertEqual(valor.resultado, Decimal('5'))

    def test_ciclo_abierto_y_ciclo_abierto_despues_de_cierre_excluidos(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.ciclos([(self.instante(26, 9), None)])
        self.ciclos([(self.instante(26, 9), self.instante(26, 12)), (self.instante(26, 14), None)])
        valor = self.calcular()
        self.assertIsNone(valor.resultado)
        self.assertIsNone(valor.cumplimiento.porcentaje)
        self.assertEqual(valor.sin_duracion_calculable, 2)

    def test_historica_sin_datos_no_inventa_duracion(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, ('aprobada',))
        valor = self.calcular()
        self.assertIsNone(valor.resultado)
        self.assertEqual(valor.sin_duracion_calculable, 1)
        self.assertTrue(any('sin historial temporal' in texto for texto in valor.observaciones))

    def test_historial_insuficiente_no_diluye_promedio_valido(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, ('aprobada',))
        valor = self.calcular()
        self.assertEqual(valor.base_utilizada, 1)
        self.assertEqual(valor.resultado, Decimal('5'))
        self.assertEqual(valor.sin_duracion_calculable, 1)

    def test_primera_reapertura_sin_ciclos_previos_es_insuficiente(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        eventos = list(aporte.actividad.historial_estados.order_by('pk'))
        HistorialEstadoActividad.objects.filter(pk__in=[eventos[0].pk]).delete()
        HistorialEstadoActividad.objects.filter(pk=eventos[1].pk).update(estado_anterior='cerrada')
        self.assertIsNone(self.calcular().resultado)

    def test_sin_creacion_pero_inicio_conocido_desde_registrada_es_calculable(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        aporte.actividad.historial_estados.filter(estado_anterior='').delete()
        self.assertEqual(self.calcular().resultado, Decimal('5'))

    def test_historial_con_timestamps_invertidos_o_cadena_rota_no_calcula(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        cierre = aporte.actividad.historial_estados.get(estado_nuevo='cerrada')
        HistorialEstadoActividad.objects.filter(pk=cierre.pk).update(fecha_hora=self.instante(26, 8))
        self.assertIsNone(self.calcular().resultado)
        HistorialEstadoActividad.objects.filter(pk=cierre.pk).update(fecha_hora=self.instante(26, 14), estado_anterior='registrada')
        self.assertIsNone(self.calcular().resultado)

    def test_historial_no_coincidente_con_estado_actual_no_calcula(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        aporte.actividad.estado = 'en_proceso'
        aporte.actividad.save(update_fields=['estado'])
        self.assertIsNone(self.calcular().resultado)

    def test_cero_horas_reales_es_resultado_y_menor_sin_limite(self):
        self.configurar(Indicador.Unidad.HORAS, '24', Indicador.Sentido.MENOR)
        instante = self.instante(26, 9)
        self.ciclos([(instante, instante)])
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('0'))
        self.assertEqual(valor.base_utilizada, 1)
        self.assertEqual(valor.cumplimiento.estado, EstadoCumplimiento.SIN_LIMITE)

    def test_precision_no_redondea_cada_ciclo(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        aporte = self.ciclos([(self.instante(26, 9), self.instante(26, 9, 15)),
                              (self.instante(26, 10), self.instante(26, 10, 15))])
        self.assertEqual(self.duracion(aporte).valor, Decimal('0.5'))

    def test_dias_lunes_martes_24_horas_no_jornada_ocho(self):
        self.configurar(Indicador.Unidad.DIAS, '5')
        self.ciclos([(self.instante(26, 12), self.instante(27, 12))])
        self.assertEqual(self.calcular().resultado, Decimal('1'))

    def test_dias_viernes_lunes_excluye_fin_de_semana(self):
        self.configurar(Indicador.Unidad.DIAS, '5')
        self.ciclos([(self.instante(23, 12), self.instante(26, 12))])
        self.assertEqual(self.calcular().resultado, Decimal('1'))

    def test_dias_fraccionarios_no_se_redondean_a_enteros(self):
        self.configurar(Indicador.Unidad.DIAS, '5')
        self.ciclos([(self.instante(26, 0), self.instante(27, 12))])
        self.assertEqual(self.calcular().resultado, Decimal('1.5'))

    def test_dias_solo_sabado_domingo_es_cero_real(self):
        self.configurar(Indicador.Unidad.DIAS, '5')
        self.ciclos([(self.instante(24, 0), self.instante(26, 0))])
        self.assertEqual(self.calcular().resultado, Decimal('0'))

    def test_dias_multiples_ciclos_y_promedio(self):
        self.configurar(Indicador.Unidad.DIAS, '5', Indicador.Sentido.MENOR)
        self.ciclos([(self.instante(23, 12), self.instante(26, 12)),
                     (self.instante(27, 0), self.instante(28, 0))])
        self.ciclos([(self.instante(26, 0), self.instante(30, 0))])
        valor = self.calcular()
        self.assertEqual(valor.resultado, Decimal('3'))
        self.assertEqual(valor.base_utilizada, 2)

    @override_settings(TIME_ZONE='America/New_York')
    def test_tiempo_transcurrido_y_fin_de_semana_con_cambio_horario(self):
        zona = ZoneInfo('America/New_York')
        inicio = datetime(2026, 3, 6, 12, tzinfo=zona)
        fin = datetime(2026, 3, 9, 12, tzinfo=zona)
        self.assertEqual(Decimal(microsegundos_habiles(inicio, fin)) / MICROSEGUNDOS_DIA, Decimal('1'))
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.ciclos([(inicio, fin)])
        self.assertEqual(self.calcular().resultado, Decimal('71'))


class ValidacionObjetivoTests(DatosMetricasMixin, TestCase):
    def test_nuevo_objetivo_cero_activo_rechazado_en_modelo(self):
        with self.assertRaises(ValidationError):
            self.crear_indicador(valor_objetivo=0)

    def test_objetivo_cero_inactivo_permitido_y_reactivacion_rechazada(self):
        indicador = self.crear_indicador(valor_objetivo=0, activo=False)
        self.entrar('administrador')
        self.client.post(reverse('sgr:indicador_estado', args=[indicador.pk]), {'activo': 'true'})
        indicador.refresh_from_db()
        self.assertFalse(indicador.activo)
        self.assertEqual(indicador.valor_objetivo, Decimal('0'))

    def test_legacy_activo_cero_consulta_sin_mutar_y_bloquea_edicion_invalida(self):
        self.configurar()
        Indicador.objects.filter(pk=self.indicador_a.pk).update(valor_objetivo=0)
        valor = self.calcular()
        self.assertEqual(valor.objetivo, Decimal('0'))
        self.assertIsNone(valor.cumplimiento.porcentaje)
        self.assertEqual(valor.cumplimiento.estado, EstadoCumplimiento.OBJETIVO_INVALIDO)
        self.entrar('administrador')
        self.assertContains(self.client.get(self.indicador_a.get_absolute_url()), 'Objetivo no calculable')
        respuesta = self.client.post(reverse('sgr:indicador_editar', args=[self.indicador_a.pk]),
            self.datos_indicador(nombre='Nombre nuevo', valor_objetivo='0'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('valor_objetivo', respuesta.context['form'].errors)
        self.indicador_a.refresh_from_db()
        self.assertEqual(self.indicador_a.valor_objetivo, Decimal('0'))

    def test_formulario_creacion_no_permite_cero(self):
        self.entrar('administrador')
        respuesta = self.client.post(reverse('sgr:indicador_crear'), self.datos_indicador(valor_objetivo='0'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('valor_objetivo', respuesta.context['form'].errors)


class MetricasPresentacionTests(DatosMetricasMixin, TestCase):
    def test_otra_presenta_unidad_personalizada_y_cumplimiento(self):
        self.configurar(Indicador.Unidad.OTRA, '100')
        aporte = self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=50)
        self.entrar('delegado')
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Resultado: 50 árboles')
        self.assertContains(respuesta, 'Cumplimiento del objetivo: 50,00%')
        self.assertContains(respuesta, 'Avance de actividades')
        self.assertContains(respuesta, 'Resultado del Indicador')

    def test_ui_distingue_none_cero_real_y_menor_sin_limite(self):
        self.configurar(Indicador.Unidad.PORCENTAJE, '80')
        self.entrar('delegado')
        self.assertContains(self.client.get(self.indicador_a.get_absolute_url()), 'Sin resultado calculable')
        self.vincular(estado_aporte=AporteIndicador.Estado.NO_CUMPLE)
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Resultado: 0 %')
        self.assertNotContains(respuesta, 'Sin resultado calculable')
        self.indicador_a.sentido = Indicador.Sentido.MENOR
        self.indicador_a.save()
        self.assertContains(self.client.get(self.indicador_a.get_absolute_url()),
                            'Cumplimiento superior al objetivo (resultado 0)')

    def test_ui_informa_temporales_excluidas(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, ('aprobada',))
        self.entrar('delegado')
        respuesta = self.client.get(self.indicador_a.get_absolute_url())
        self.assertContains(respuesta, 'Sin resultado calculable')
        self.assertContains(respuesta, '1 sin duración calculable')
        self.assertContains(respuesta, 'sin historial temporal')

    def test_no_hay_fuga_territorial_ni_cambio_de_roles(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            self.assertEqual(self.client.get(self.indicador_b.get_absolute_url()).status_code, 404)
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            self.assertEqual(self.client.get(self.indicador_a.get_absolute_url()).status_code, 403)
        self.entrar('administrador')
        self.assertEqual(self.client.get(self.indicador_b.get_absolute_url()).status_code, 200)

    def test_lecturas_no_generan_auditoria_ni_modifican_fuentes(self):
        self.configurar()
        self.vincular(estado_aporte=AporteIndicador.Estado.CUMPLE)
        originales = list(AporteIndicador.objects.values())
        auditorias = RegistroAuditoria.objects.count()
        self.entrar('delegado')
        for _ in range(2):
            self.calcular()
            self.client.get(self.indicador_a.get_absolute_url())
        self.assertEqual(list(AporteIndicador.objects.values()), originales)
        self.assertEqual(RegistroAuditoria.objects.count(), auditorias)

    def test_consultas_constantes_sin_n_mas_uno_temporal(self):
        self.configurar(Indicador.Unidad.HORAS, '24')
        self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        with CaptureQueriesContext(connection) as pequeno:
            self.calcular()
        for _ in range(15):
            self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        with CaptureQueriesContext(connection) as grande:
            valor = self.calcular()
        self.assertEqual(len(pequeno), len(grande))
        self.assertLessEqual(len(grande), 4)
        self.assertEqual(valor.base_utilizada, 16)
        self.assertEqual(valor.resultado, Decimal('5'))
