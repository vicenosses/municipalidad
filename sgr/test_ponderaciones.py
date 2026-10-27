from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from auditoria.models import RegistroAuditoria
from auditoria.permisos import registros_autorizados
from sgr.calculos import calcular_avance_indicador, calcular_resultado_indicador, calcular_resultados_indicadores
from sgr.aportes import proponer_aporte
from sgr.forms import IndicadorForm
from sgr.models import AporteIndicador, HistorialPonderacionIndicador, Indicador
from sgr.ponderaciones import calcular_ponderacion_indicador, calcular_resultado_meta
from sgr.test_metricas import DatosMetricasMixin


class DatosPonderacionesMixin(DatosMetricasMixin):
    def setUp(self):
        super().setUp()
        for indicador in (self.indicador_a, self.otro_indicador):
            indicador.activo = False
            indicador.save()

    def nuevo(self, peso=None, **kwargs):
        datos = dict(meta=self.meta_a, nombre=f'Ponderado {Indicador.objects.count()}',
            unidad_medida=Indicador.Unidad.OTRA, unidad_personalizada='árboles',
            sentido=Indicador.Sentido.MAYOR, valor_objetivo=100, ponderacion=peso)
        datos.update(kwargs)
        return Indicador.objects.create(**datos)

    def evaluado(self, peso, cumplimiento):
        if cumplimiento is None:
            return self.nuevo(peso, unidad_medida='porcentaje', unidad_personalizada='')
        indicador = self.nuevo(peso)
        aporte = self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, ('aprobada',), indicador)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=Decimal(str(cumplimiento)))
        return indicador

    def ajustar(self, indicador, peso, motivo='', rol='delegado', **kwargs):
        indicador.ponderacion = Decimal(str(peso)) if peso is not None else None
        indicador._motivo_ponderacion = motivo
        indicador._actor_ponderacion = self.usuarios[rol]
        indicador._request_ponderacion = self.request(rol)
        indicador.save(**kwargs)

    def agregado(self):
        return calcular_resultado_meta(self.meta_a)


class PonderacionModeloTests(DatosPonderacionesMixin, TestCase):
    def test_peso_valido_decimal_y_completo(self):
        a = self.nuevo('12.50')
        b = self.nuevo('87.50')
        self.assertEqual(a.ponderacion, Decimal('12.50'))
        self.assertEqual(b.ponderacion, Decimal('87.50'))
        self.assertTrue(self.agregado().configuracion_completa)

    def test_negativos_mayores_cien_no_finitos_y_precision_rechazados(self):
        for peso in ('-0.01', '100.01', 'NaN', 'Infinity', '-Infinity', 'no-numero', '12.345'):
            with self.subTest(peso=peso), self.assertRaises(ValidationError):
                self.nuevo(peso)

    def test_cero_activo_rechazado_historico_inactivo_permitido(self):
        with self.assertRaises(ValidationError):
            self.nuevo('0')
        cero = self.nuevo('0', activo=False)
        nulo = self.nuevo(None, activo=False)
        self.assertEqual(cero.ponderacion_display, '0%')
        self.assertEqual(nulo.ponderacion_display, 'Ponderación no configurada')

    def test_indicadores_anteriores_sin_peso_no_reciben_peso_ficticio(self):
        self.indicador_a.refresh_from_db()
        self.assertIsNone(self.indicador_a.ponderacion)
        self.assertEqual(self.indicador_a.historial_ponderacion.count(), 0)
        self.nuevo(None)
        resultado = self.agregado()
        self.assertEqual(resultado.ponderacion_asignada, Decimal('0'))
        self.assertEqual(resultado.ponderacion_pendiente, Decimal('100'))
        self.assertEqual(resultado.sin_ponderacion, 1)
        self.assertFalse(resultado.configuracion_completa)

    def test_suma_superior_a_cien_rechaza_creacion(self):
        self.nuevo('80')
        with self.assertRaises(ValidationError):
            self.nuevo('30')
        self.assertEqual(self.agregado().ponderacion_asignada, Decimal('80'))

    def test_suma_superior_a_cien_rechaza_edicion(self):
        self.nuevo('80')
        b = self.nuevo('20')
        with self.assertRaises(ValidationError):
            self.ajustar(b, '30')
        b.refresh_from_db()
        self.assertEqual(b.ponderacion, Decimal('20'))
        self.assertFalse(b.historial_ponderacion.exists())

    def test_construccion_progresiva_sin_redistribucion(self):
        self.nuevo('40')
        parcial = self.agregado()
        self.assertEqual(parcial.ponderacion_pendiente, Decimal('60'))
        self.assertFalse(parcial.configuracion_completa)
        self.nuevo('35')
        self.assertEqual(self.agregado().ponderacion_pendiente, Decimal('25'))
        self.nuevo('25')
        self.assertTrue(self.agregado().configuracion_completa)

    def test_cien_con_otro_indicador_sin_peso_sigue_incompleta(self):
        self.nuevo('100')
        self.nuevo(None)
        resultado = self.agregado()
        self.assertEqual(resultado.ponderacion_asignada, Decimal('100'))
        self.assertEqual(resultado.sin_ponderacion, 1)
        self.assertFalse(resultado.configuracion_completa)

    def test_inactivo_no_suma_ni_recibe_reasignacion(self):
        self.nuevo('40')
        b = self.nuevo('60')
        b.activo = False
        b.save()
        resultado = self.agregado()
        self.assertEqual(resultado.ponderacion_asignada, Decimal('40'))
        self.assertEqual(resultado.ponderacion_pendiente, Decimal('60'))
        b.refresh_from_db()
        self.assertEqual(b.ponderacion, Decimal('60'))
        self.assertFalse(resultado.configuracion_completa)

    def test_reactivacion_revalida_suma_y_cero(self):
        self.nuevo('80')
        for peso in ('30', '0'):
            antiguo = self.nuevo(peso, activo=False)
            antiguo.activo = True
            with self.subTest(peso=peso), self.assertRaises(ValidationError):
                antiguo.save()
            antiguo.refresh_from_db()
            self.assertFalse(antiguo.activo)

    def test_otra_meta_tiene_presupuesto_independiente(self):
        self.nuevo('100')
        otro = self.nuevo('100', meta=self.meta_b)
        self.assertEqual(otro.ponderacion, Decimal('100'))

    def test_constraint_de_rango_en_base_de_datos(self):
        indicador = self.nuevo('40')
        for peso in ('-1', '101'):
            with self.subTest(peso=peso), self.assertRaises(IntegrityError), transaction.atomic():
                Indicador.objects.filter(pk=indicador.pk).update(ponderacion=peso)

    def test_update_fields_no_omite_peso_o_estado_modificado(self):
        indicador = self.nuevo('40')
        with self.assertRaises(ValidationError):
            self.ajustar(indicador, '50', update_fields=['nombre'])
        indicador.refresh_from_db()
        indicador.activo = False
        with self.assertRaises(ValidationError):
            indicador.save(update_fields=['nombre'])

    def test_conserva_proteccion_desactivar_con_aportes(self):
        indicador = self.evaluado('40', '80')
        indicador.activo = False
        with self.assertRaises(ValidationError):
            indicador.save()

    def test_guardado_revalida_suma_despues_de_validar_formulario(self):
        a = self.nuevo(None)
        b = self.nuevo(None)
        form = IndicadorForm(self.datos_indicador(nombre=a.nombre, ponderacion='80'),
            request=self.request('delegado'), instance=a)
        self.assertTrue(form.is_valid(), form.errors)
        self.ajustar(b, '30')
        with self.assertRaises(ValidationError):
            form.save()
        a.refresh_from_db()
        self.assertIsNone(a.ponderacion)
        self.assertEqual(self.agregado().ponderacion_asignada, Decimal('30'))


class PonderacionHistorialTests(DatosPonderacionesMixin, TestCase):
    def test_configuracion_sin_uso_registra_actor_y_nulo_anterior(self):
        indicador = self.nuevo(None)
        self.ajustar(indicador, '40')
        historial = indicador.historial_ponderacion.get()
        self.assertIsNone(historial.valor_anterior)
        self.assertEqual(historial.valor_nuevo, Decimal('40'))
        self.assertEqual(historial.usuario, self.usuarios['delegado'])
        self.assertIsNotNone(historial.creado_en)
        self.assertEqual(historial.motivo, '')
        self.assertTrue(RegistroAuditoria.objects.filter(accion='cambiar_ponderacion_indicador',
            modelo='sgr.Indicador', objeto_id=str(indicador.pk)).exists())

    def test_cambio_sin_actor_rechazado(self):
        indicador = self.nuevo('40')
        indicador.ponderacion = Decimal('50')
        with self.assertRaises(ValidationError):
            indicador.save()

    def test_con_aportes_exige_motivo(self):
        indicador = self.evaluado('40', '80')
        with self.assertRaises(ValidationError):
            self.ajustar(indicador, '50', motivo='   ')
        indicador.refresh_from_db()
        self.assertEqual(indicador.ponderacion, Decimal('40'))
        self.assertFalse(indicador.historial_ponderacion.exists())

    def test_cambio_relevante_historial_y_recalculo_sin_alterar_9f(self):
        indicador = self.evaluado('40', '80')
        anterior = calcular_ponderacion_indicador(indicador)
        self.ajustar(indicador, '50', motivo='  Revisión de prioridades  ')
        nuevo = calcular_ponderacion_indicador(indicador)
        historial = indicador.historial_ponderacion.get()
        self.assertEqual((historial.valor_anterior, historial.valor_nuevo), (Decimal('40'), Decimal('50')))
        self.assertEqual(historial.motivo, 'Revisión de prioridades')
        self.assertEqual(nuevo.resultado_ponderado, Decimal('40'))
        self.assertEqual(nuevo.metrica, anterior.metrica)
        self.assertEqual(indicador.historial_objetivo.count(), 0)

    def test_desconfigurar_peso_con_uso_exige_motivo_y_conserva_none(self):
        indicador = self.evaluado('40', '80')
        self.ajustar(indicador, None, motivo='Retirar de la configuración vigente')
        fila = calcular_ponderacion_indicador(indicador)
        self.assertEqual(fila.estado, 'sin_ponderacion')
        self.assertIsNone(fila.resultado_ponderado)
        self.assertIsNone(indicador.historial_ponderacion.get().valor_nuevo)

    def test_error_de_historial_revierte_peso_y_auditoria(self):
        indicador = self.evaluado('40', '80')
        cantidad = RegistroAuditoria.objects.count()
        with patch('sgr.models.HistorialPonderacionIndicador.objects.create', side_effect=RuntimeError('Fallo')):
            with self.assertRaises(RuntimeError):
                self.ajustar(indicador, '50', motivo='Cambio controlado')
        indicador.refresh_from_db()
        self.assertEqual(indicador.ponderacion, Decimal('40'))
        self.assertEqual(RegistroAuditoria.objects.count(), cantidad)

    def test_guardar_sin_cambio_no_duplica_historial(self):
        indicador = self.nuevo('40')
        self.ajustar(indicador, '50')
        self.ajustar(indicador, '50')
        self.assertEqual(indicador.historial_ponderacion.count(), 1)

    def test_aporte_trasladado_conserva_obligacion_de_motivo_historico(self):
        a = self.nuevo('40')
        b = self.nuevo('40')
        aporte = self.asociar(a)
        proponer_aporte(self.request(), self.actividad, b, Decimal('20'), aporte.version)
        self.assertFalse(a.aportes.exists())
        self.assertTrue(a.tiene_vinculaciones)
        with self.assertRaises(ValidationError):
            self.ajustar(a, '50')


class PonderacionCalculoTests(DatosPonderacionesMixin, TestCase):
    def test_caso_1_completo_94(self):
        for peso, cumplimiento in (('50', '80'), ('30', '100'), ('20', '120')):
            self.evaluado(peso, cumplimiento)
        resultado = self.agregado()
        valores = [f.resultado_ponderado for f in resultado.indicadores if f.indicador.activo]
        self.assertEqual(valores, [Decimal('40'), Decimal('30'), Decimal('24')])
        self.assertEqual(resultado.resultado_ponderado_bruto, Decimal('94'))
        self.assertEqual(resultado.cobertura_calculable, Decimal('100'))
        self.assertEqual(resultado.cumplimiento_normalizado, Decimal('94.00'))
        self.assertTrue(resultado.configuracion_completa)

    def test_caso_2_parcial_62_cobertura_70_normalizado_88_57(self):
        for peso, cumplimiento in (('40', '80'), ('30', '100'), ('30', None)):
            self.evaluado(peso, cumplimiento)
        resultado = self.agregado()
        self.assertEqual(resultado.resultado_ponderado_bruto, Decimal('62'))
        self.assertEqual(resultado.cobertura_calculable, Decimal('70'))
        self.assertEqual(resultado.cumplimiento_normalizado, Decimal('88.57'))
        self.assertEqual(resultado.sin_resultado, 1)
        self.assertTrue(resultado.configuracion_completa)

    def test_caso_3_cero_real_incluido_en_cobertura(self):
        self.evaluado('50', '0')
        self.evaluado('50', '100')
        resultado = self.agregado()
        self.assertEqual(resultado.resultado_ponderado_bruto, Decimal('50'))
        self.assertEqual(resultado.cobertura_calculable, Decimal('100'))
        self.assertEqual(resultado.cumplimiento_normalizado, Decimal('50.00'))
        self.assertEqual(resultado.sin_resultado, 0)

    def test_caso_4_sobrecumplimiento_140(self):
        self.evaluado('40', '200')
        self.evaluado('60', '100')
        resultado = self.agregado()
        self.assertEqual(resultado.resultado_ponderado_bruto, Decimal('140'))
        self.assertEqual(resultado.cumplimiento_normalizado, Decimal('140.00'))

    def test_supera_150_sin_tope_y_peso_decimal(self):
        indicador = self.evaluado('12.5', '200')
        self.assertEqual(calcular_ponderacion_indicador(indicador).resultado_ponderado, Decimal('25'))
        self.assertEqual(self.agregado().cumplimiento_normalizado, Decimal('200.00'))

    def test_individual_40_por_80_es_32(self):
        indicador = self.evaluado('40', '80')
        fila = calcular_ponderacion_indicador(indicador)
        self.assertEqual(fila.resultado_ponderado, Decimal('32'))
        self.assertEqual(fila.metrica.cumplimiento.porcentaje, Decimal('80'))

    def test_sin_resultado_no_se_convierte_en_cero(self):
        indicador = self.evaluado('100', None)
        self.assertIsNone(calcular_ponderacion_indicador(indicador).resultado_ponderado)
        resultado = self.agregado()
        self.assertEqual(resultado.cobertura_calculable, Decimal('0'))
        self.assertIsNone(resultado.resultado_ponderado_bruto)
        self.assertIsNone(resultado.cumplimiento_normalizado)

    def test_cero_real_total_es_cero_y_cobertura_cien(self):
        self.evaluado('100', '0')
        resultado = self.agregado()
        self.assertEqual(resultado.cobertura_calculable, Decimal('100'))
        self.assertEqual(resultado.cumplimiento_normalizado, Decimal('0.00'))

    def test_sin_peso_no_inventa_peso_aunque_tenga_resultado(self):
        indicador = self.evaluado(None, '80')
        fila = calcular_ponderacion_indicador(indicador)
        self.assertEqual(fila.metrica.resultado, Decimal('80'))
        self.assertIsNone(fila.resultado_ponderado)
        self.assertEqual(self.agregado().cobertura_calculable, Decimal('0'))

    def test_sin_limite_no_inventa_porcentaje_ponderado(self):
        indicador = self.nuevo('100', unidad_medida='cantidad', unidad_personalizada='', sentido='menor')
        fila = calcular_ponderacion_indicador(indicador)
        self.assertEqual(fila.estado, 'sin_limite')
        self.assertIsNone(fila.resultado_ponderado)
        resultado = self.agregado()
        self.assertEqual(resultado.sin_limite, 1)
        self.assertEqual(resultado.cobertura_calculable, Decimal('0'))
        self.assertIsNone(resultado.cumplimiento_normalizado)

    def test_objetivo_historico_cero_no_contribuye_cobertura(self):
        indicador = self.evaluado('100', '80')
        Indicador.objects.filter(pk=indicador.pk).update(valor_objetivo=0)
        resultado = self.agregado()
        self.assertEqual(resultado.sin_resultado, 1)
        self.assertEqual(resultado.cobertura_calculable, Decimal('0'))

    def test_9e_binario_y_9f_independientes_de_ponderacion(self):
        indicador = self.evaluado('40', '80')
        aporte = self.vincular('en_proceso', AporteIndicador.Estado.CUMPLE, ('aprobada',), indicador)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=20)
        antes = calcular_resultado_indicador(indicador)
        operativo = calcular_avance_indicador(indicador)
        self.assertEqual(operativo.porcentaje_avance, Decimal('50'))
        self.assertEqual(operativo.puntos_ponderados, Decimal('1'))
        self.ajustar(indicador, '60', motivo='Redistribuir prioridades')
        self.assertEqual(calcular_resultado_indicador(indicador), antes)
        self.assertEqual(calcular_avance_indicador(indicador), operativo)

    def test_lote_y_9f_individual_coinciden_para_todas_las_unidades(self):
        indicadores = []
        for unidad in Indicador.Unidad.values:
            indicador = self.nuevo('20', unidad_medida=unidad,
                unidad_personalizada='árboles' if unidad == 'otra' else '')
            self.indicador_a = indicador
            self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
            indicadores.append(indicador)
        lote = calcular_resultados_indicadores(indicadores)
        for indicador in indicadores:
            self.assertEqual(lote[indicador.pk], calcular_resultado_indicador(indicador))

    def test_lecturas_no_generan_auditoria_ni_historial(self):
        self.evaluado('40', '80')
        antes = (RegistroAuditoria.objects.count(), HistorialPonderacionIndicador.objects.count(),
                 list(Indicador.objects.values()), list(AporteIndicador.objects.values()))
        self.entrar('delegado')
        for _ in range(2):
            self.agregado()
            self.client.get(self.meta_a.get_absolute_url())
        despues = (RegistroAuditoria.objects.count(), HistorialPonderacionIndicador.objects.count(),
                   list(Indicador.objects.values()), list(AporteIndicador.objects.values()))
        self.assertEqual(antes, despues)

    def test_consultas_constantes_con_multiples_indicadores_temporales(self):
        def temporal():
            indicador = self.nuevo('5', unidad_medida='horas', unidad_personalizada='')
            self.indicador_a = indicador
            self.ciclos([(self.instante(26, 9), self.instante(26, 14))])
        temporal()
        with CaptureQueriesContext(connection) as chico:
            self.agregado()
        for _ in range(10):
            temporal()
        with CaptureQueriesContext(connection) as grande:
            resultado = self.agregado()
        self.assertEqual(len(chico), len(grande))
        self.assertLessEqual(len(grande), 3)
        self.assertEqual(resultado.cobertura_calculable, Decimal('55'))


class PonderacionVistasTests(DatosPonderacionesMixin, TestCase):
    def test_admin_delegado_coordinador_configuran_peso(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            nombre = f'Peso {rol}'
            respuesta = self.client.post(reverse('sgr:indicador_crear'),
                self.datos_indicador(nombre=nombre, ponderacion='20'))
            self.assertEqual(respuesta.status_code, 302)
            indicador = Indicador.objects.get(nombre=nombre)
            respuesta = self.client.post(reverse('sgr:indicador_editar', args=[indicador.pk]),
                self.datos_indicador(nombre=nombre, ponderacion='25'))
            self.assertEqual(respuesta.status_code, 302)
            indicador.refresh_from_db()
            self.assertEqual(indicador.ponderacion, Decimal('25'))
            self.assertEqual(indicador.historial_ponderacion.get().usuario, self.usuarios[rol])

    def test_funcionario_y_verificador_no_administran(self):
        indicador = self.nuevo('40')
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            for ruta in (reverse('sgr:indicador_crear'), reverse('sgr:indicador_editar', args=[indicador.pk])):
                self.assertEqual(self.client.post(ruta, self.datos_indicador(ponderacion='50')).status_code, 403)
        indicador.refresh_from_db()
        self.assertEqual(indicador.ponderacion, Decimal('40'))

    def test_otro_territorio_no_edita_ni_ve_meta(self):
        indicador = self.nuevo('40', meta=self.meta_b)
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            ruta = reverse('sgr:indicador_editar', args=[indicador.pk])
            self.assertEqual(self.client.post(ruta, self.datos_indicador(ponderacion='50')).status_code, 404)
            self.assertEqual(self.client.get(self.meta_b.get_absolute_url()).status_code, 404)
        self.entrar('administrador')
        self.assertEqual(self.client.get(self.meta_b.get_absolute_url()).status_code, 200)

    def test_suma_excedida_se_muestra_como_error_backend(self):
        self.nuevo('80')
        self.entrar('delegado')
        respuesta = self.client.post(reverse('sgr:indicador_crear'), self.datos_indicador(ponderacion='30'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('ponderacion', respuesta.context['form'].errors)

    def test_formulario_exige_motivo_en_indicador_utilizado(self):
        indicador = self.evaluado('40', '80')
        self.entrar('coordinador')
        ruta = reverse('sgr:indicador_editar', args=[indicador.pk])
        datos = self.datos_indicador(nombre=indicador.nombre, unidad_medida='otra',
            unidad_personalizada='árboles', ponderacion='50')
        respuesta = self.client.post(ruta, datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('ponderacion', respuesta.context['form'].errors)
        datos['motivo_ponderacion'] = 'Prioridad revisada'
        self.assertEqual(self.client.post(ruta, datos).status_code, 302)

    def test_detalle_meta_cobertura_y_normalizacion_visibles(self):
        for peso, cumplimiento in (('40', '80'), ('30', '100'), ('30', None)):
            self.evaluado(peso, cumplimiento)
        self.entrar('delegado')
        respuesta = self.client.get(self.meta_a.get_absolute_url())
        for texto in ('Ponderación completa', '70,00%', '62,00 puntos porcentuales', '88,57%',
                      'Indicadores activos sin cumplimiento numérico calculable: 1'):
            self.assertContains(respuesta, texto)

    def test_detalle_indicador_separa_avance_metrica_y_ponderacion(self):
        indicador = self.evaluado('20', '120')
        self.entrar('delegado')
        respuesta = self.client.get(indicador.get_absolute_url())
        for texto in ('Avance de actividades', 'Resultado del Indicador', 'Ponderación del Indicador',
                      'Resultado ponderado: 24,00%'):
            self.assertContains(respuesta, texto)

    def test_meta_incompleta_y_sin_resultado_no_se_ocultan(self):
        self.evaluado('75', None)
        self.entrar('delegado')
        respuesta = self.client.get(self.meta_a.get_absolute_url())
        for texto in ('Configuración incompleta', '75,00%', '25,00%', 'Sin resultado calculable'):
            self.assertContains(respuesta, texto)

    def test_auditoria_ponderacion_mantiene_territorialidad(self):
        indicador = self.nuevo('40', meta=self.meta_b)
        self.ajustar(indicador, '50', rol='administrador')
        registros = RegistroAuditoria.objects.filter(accion='cambiar_ponderacion_indicador')
        self.assertFalse(registros_autorizados(self.request('delegado'), registros).exists())
        request_global = self.request('administrador')
        request_global.session['delegacion_activa_id'] = 'global'
        self.assertTrue(registros_autorizados(request_global, registros).exists())
