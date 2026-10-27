from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sgr.dashboard import calcular_avance_esperado, calcular_semaforo, obtener_periodo_vigente
from sgr.models import AporteIndicador, Indicador, Meta, Periodo
from sgr.ponderaciones import calcular_resultado_meta, calcular_resultados_metas
from sgr.test_ponderaciones import DatosPonderacionesMixin
from usuarios.models import Perfil


class SemaforoTests(SimpleTestCase):
    def test_verde_en_igualdad_y_por_encima(self):
        for real in ('50', '80', '231', '834'):
            with self.subTest(real=real):
                self.assertEqual(calcular_semaforo(Decimal(real), Decimal('50')).estado, 'verde')

    def test_naranjo_incluye_exactamente_sesenta_por_ciento(self):
        for real in ('30', '30.01', '49.99'):
            with self.subTest(real=real):
                self.assertEqual(calcular_semaforo(Decimal(real), Decimal('50')).estado, 'naranjo')

    def test_rojo_incluye_cero_real(self):
        for real in ('0', '29.99'):
            with self.subTest(real=real):
                self.assertEqual(calcular_semaforo(Decimal(real), Decimal('50')).estado, 'rojo')

    def test_ausencia_de_datos_no_es_rojo(self):
        self.assertEqual(calcular_semaforo(None, Decimal('50')).estado, 'sin_datos')

    def test_esperado_cero_o_invalido_no_tiene_color(self):
        for esperado in (None, Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('Infinity')):
            with self.subTest(esperado=esperado):
                self.assertEqual(calcular_semaforo(Decimal('100'), esperado).estado, 'sin_datos')

    def test_real_invalido_no_tiene_color(self):
        for real in ('-1', 'NaN', 'Infinity'):
            with self.subTest(real=real):
                self.assertEqual(calcular_semaforo(Decimal(real), Decimal('50')).estado, 'sin_datos')


class CalendarioDashboardTests(SimpleTestCase):
    def setUp(self):
        self.periodo = SimpleNamespace(fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 10, 10))

    def test_calendario_inclusivo_al_quinto_dia(self):
        self.assertEqual(calcular_avance_esperado(self.periodo, date(2026, 10, 5)), Decimal('50'))

    def test_periodo_futuro_esperado_cero_y_sin_color(self):
        esperado = calcular_avance_esperado(self.periodo, date(2026, 9, 30))
        self.assertEqual(esperado, Decimal('0'))
        self.assertEqual(calcular_semaforo(Decimal('0'), esperado).estado, 'sin_datos')

    def test_inicio_y_fin_incluidos(self):
        self.assertEqual(calcular_avance_esperado(self.periodo, date(2026, 10, 1)), Decimal('10'))
        self.assertEqual(calcular_avance_esperado(self.periodo, date(2026, 10, 10)), Decimal('100'))

    def test_periodo_vencido_no_extrapola(self):
        self.assertEqual(calcular_avance_esperado(self.periodo, date(2028, 10, 1)), Decimal('100'))

    def test_periodo_de_un_dia_no_divide_por_cero(self):
        self.periodo.fecha_fin = self.periodo.fecha_inicio
        self.assertEqual(calcular_avance_esperado(self.periodo, self.periodo.fecha_inicio), Decimal('100'))

    def test_fechas_invertidas_y_ausentes_no_calculan(self):
        for inicio, fin in ((date(2026, 10, 11), date(2026, 10, 10)), (None, date(2026, 10, 10)),
                            (date(2026, 10, 1), None)):
            with self.subTest(inicio=inicio, fin=fin):
                periodo = SimpleNamespace(fecha_inicio=inicio, fecha_fin=fin)
                self.assertIsNone(calcular_avance_esperado(periodo, date(2026, 10, 5)))

    def test_incluye_fin_de_semana_y_anio_bisiesto(self):
        periodo = SimpleNamespace(fecha_inicio=date(2024, 2, 28), fecha_fin=date(2024, 3, 2))
        self.assertEqual(calcular_avance_esperado(periodo, date(2024, 2, 29)), Decimal('50'))


class DashboardSGRTests(DatosPonderacionesMixin, TestCase):
    def setUp(self):
        super().setUp()
        fecha_patch = patch('sgr.dashboard.timezone.localdate', return_value=date(2026, 10, 26))
        fecha_patch.start()
        self.addCleanup(fecha_patch.stop)
        self.entrar('administrador')

    def respuesta(self):
        return self.client.get(reverse('home'))

    def dashboard(self):
        return self.respuesta().context['dashboard']

    def fila_a(self):
        return next(fila for fila in self.dashboard()['filas'] if fila.meta.pk == self.meta_a.pk)

    def test_anonimo_requiere_login(self):
        self.client.logout()
        self.assertRedirects(self.respuesta(), reverse('login') + '?next=/', fetch_redirect_response=False)

    def test_muestra_periodo_fechas_contexto_y_limitacion_calendario(self):
        respuesta = self.respuesta()
        for texto in ('Dashboard SGR', self.periodo.nombre, '01/01/2026', '31/12/2026',
                      '26/10/2026', 'Global: todas las delegaciones', 'No descuenta vacaciones'):
            self.assertContains(respuesta, texto)

    def test_administrador_perfil_respeta_contexto_territorial_seleccionado(self):
        sesion = self.client.session
        sesion['delegacion_activa_id'] = self.a.pk
        sesion.save()
        dashboard = self.dashboard()
        self.assertEqual({fila.meta.pk for fila in dashboard['filas']}, {self.meta_a.pk})
        self.assertEqual(dashboard['contexto_territorial'], self.a)

    def test_superusuario_sin_perfil_territorial_tiene_vista_global(self):
        usuario = get_user_model().objects.create_superuser('super', 'super@example.com', 'clave')
        self.client.force_login(usuario)
        self.assertEqual(self.dashboard()['total_metas'], 2)

    def test_cuatro_roles_territoriales_solo_ven_sus_metas(self):
        self.evaluado('100', '231')
        for rol in ('delegado', 'coordinador', 'funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.entrar(rol)
                respuesta = self.respuesta()
                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.context['dashboard']['total_metas'], 1)
                self.assertContains(respuesta, self.meta_a.nombre)
                self.assertNotContains(respuesta, self.meta_b.nombre)
                self.assertNotContains(respuesta, 'Información exclusiva B')
                self.assertEqual(respuesta.context['dashboard']['filas'][0].resultado.cumplimiento_normalizado,
                                 Decimal('231'))

    def test_enlaces_detalle_segun_permisos_existentes(self):
        for rol in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            with self.subTest(rol=rol):
                self.entrar(rol)
                respuesta = self.respuesta()
                enlace = f'href="{self.meta_a.get_absolute_url()}"'
                if rol in ('administrador', 'delegado', 'coordinador'):
                    self.assertContains(respuesta, enlace)
                    self.assertEqual(self.client.get(self.meta_a.get_absolute_url()).status_code, 200)
                else:
                    self.assertNotContains(respuesta, enlace)
                    self.assertEqual(self.client.get(self.meta_a.get_absolute_url()).status_code, 403)

    def test_delegacion_de_sesion_no_autorizada_no_expone_otra(self):
        self.entrar('funcionario')
        sesion = self.client.session
        sesion['delegacion_activa_id'] = self.b.pk
        sesion.save()
        respuesta = self.respuesta()
        self.assertContains(respuesta, self.meta_a.nombre)
        self.assertNotContains(respuesta, self.meta_b.nombre)

    def test_sin_delegacion_autorizada_no_muestra_metas_ni_contadores_globales(self):
        self.usuarios['funcionario'].perfil.delegaciones.clear()
        self.entrar('funcionario')
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'No tiene una delegación autorizada activa')
        self.assertEqual(respuesta.context['dashboard']['filas'], [])
        for campo in ('total_usuarios', 'total_actividades', 'evidencias_pendientes', 'compromisos_proximos'):
            self.assertEqual(respuesta.context[campo], 0)
        self.assertNotContains(respuesta, self.meta_b.nombre)

    def test_delegacion_inactiva_no_muestra_metas(self):
        self.a.activa = False
        self.a.save()
        self.entrar('delegado')
        self.assertEqual(self.dashboard()['filas'], [])

    def test_rol_inactivo_no_muestra_datos(self):
        rol = self.usuarios['funcionario'].perfil.rol
        rol.activo = False
        rol.save()
        self.entrar('funcionario')
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'No tiene un rol habilitado')
        self.assertEqual(respuesta.context['dashboard']['filas'], [])
        self.assertEqual(respuesta.context['total_usuarios'], 0)

    def test_usuarios_activos_contados_solo_en_delegacion_autorizada(self):
        usuario = get_user_model().objects.create_user('exclusivo-b')
        Perfil.objects.filter(usuario=usuario).update(delegacion=self.b)
        usuario.perfil.delegaciones.add(self.b)
        self.entrar('delegado')
        self.assertEqual(self.respuesta().context['total_usuarios'],
                         Perfil.objects.filter(activo=True, delegaciones=self.a).count())

    def test_sin_periodo_activo_vigente_no_elige_futuro(self):
        Periodo.objects.filter(pk=self.periodo.pk).update(activo=False)
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'No hay un período activo vigente')
        self.assertIsNone(respuesta.context['dashboard']['periodo'])
        self.assertEqual(respuesta.context['dashboard']['filas'], [])

    def test_solo_periodos_vencidos_no_son_actuales(self):
        with patch('sgr.dashboard.timezone.localdate', return_value=date(2028, 1, 1)):
            self.assertIsNone(self.dashboard()['periodo'])

    def test_solo_periodos_futuros_no_son_actuales(self):
        with patch('sgr.dashboard.timezone.localdate', return_value=date(2025, 1, 1)):
            self.assertIsNone(self.dashboard()['periodo'])

    def test_periodos_activos_superpuestos_no_se_eligen_arbitrariamente(self):
        Periodo.objects.filter(pk=self.otro_periodo.pk).update(
            fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 11, 1))
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'fechas inválidas o superpuestas')
        self.assertIsNone(respuesta.context['dashboard']['periodo'])
        self.assertEqual(respuesta.context['dashboard']['filas'], [])

    def test_periodo_historico_inactivo_superpuesto_no_interfiere(self):
        Periodo.objects.filter(pk=self.otro_periodo.pk).update(
            activo=False, fecha_inicio=date(2026, 10, 1), fecha_fin=date(2026, 11, 1))
        self.assertEqual(self.dashboard()['periodo'], self.periodo)

    def test_extremos_del_periodo_son_vigentes(self):
        for hoy in (date(2026, 1, 1), date(2026, 12, 31)):
            with self.subTest(hoy=hoy):
                self.assertEqual(obtener_periodo_vigente(hoy)[0], self.periodo)

    def test_sin_metas_muestra_estado_informativo(self):
        Meta.objects.filter(periodo=self.periodo).update(activo=False)
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'No hay metas activas para este período')
        self.assertEqual(respuesta.context['dashboard']['total_metas'], 0)

    def test_metas_inactivas_y_de_otro_periodo_excluidas(self):
        Meta.objects.filter(pk=self.meta_a.pk).update(activo=False)
        self.crear_meta(periodo=self.otro_periodo, nombre='Meta futura excluida')
        dashboard = self.dashboard()
        self.assertEqual([fila.meta.pk for fila in dashboard['filas']], [self.meta_b.pk])

    def test_sin_indicadores_activos_no_es_cero_real(self):
        fila = self.fila_a()
        self.assertIsNone(fila.resultado.cumplimiento_normalizado)
        self.assertEqual(fila.semaforo.estado, 'sin_datos')
        self.assertEqual(fila.resultado.cobertura_calculable, Decimal('0'))

    def test_cero_real_tiene_cobertura_y_rojo(self):
        self.nuevo('100', unidad_medida='cantidad', unidad_personalizada='')
        fila = self.fila_a()
        self.assertEqual(fila.resultado.cumplimiento_normalizado, Decimal('0'))
        self.assertEqual(fila.resultado.cobertura_calculable, Decimal('100'))
        self.assertEqual(fila.semaforo.estado, 'rojo')

    def test_sin_evaluados_no_se_convierte_a_cero(self):
        self.evaluado('100', None)
        fila = self.fila_a()
        self.assertIsNone(fila.resultado.cumplimiento_normalizado)
        self.assertEqual(fila.semaforo.estado, 'sin_datos')

    def test_sin_limite_se_muestra_sin_inventar_cero(self):
        self.nuevo('100', sentido='menor', unidad_medida='cantidad', unidad_personalizada='')
        fila = self.fila_a()
        self.assertIsNone(fila.resultado.cumplimiento_normalizado)
        self.assertEqual(fila.resultado.sin_limite, 1)
        self.assertEqual(fila.semaforo.estado, 'sin_datos')
        self.assertContains(self.respuesta(), 'Indicadores sin límite numérico: 1')

    def test_sobrecumplimiento_se_preserva_y_muestra_verde(self):
        self.evaluado('100', '231')
        fila = self.fila_a()
        self.assertEqual(fila.resultado.cumplimiento_normalizado, Decimal('231'))
        self.assertEqual(fila.semaforo.estado, 'verde')
        self.assertContains(self.respuesta(), '231,00%')

    def test_cobertura_parcial_y_ponderaciones_incompletas_visibles(self):
        self.evaluado('40', '120')
        self.evaluado('30', None)
        self.nuevo(None)
        fila = self.fila_a()
        self.assertEqual(fila.resultado.cumplimiento_normalizado, Decimal('120'))
        self.assertEqual(fila.resultado.cobertura_calculable, Decimal('40'))
        self.assertFalse(fila.resultado.configuracion_completa)
        respuesta = self.respuesta()
        self.assertContains(respuesta, 'Cobertura parcial')
        self.assertContains(respuesta, 'Incompletas')
        self.assertContains(respuesta, 'Sin configurar: 1')

    def test_resumen_cuenta_colores_y_calculables(self):
        self.evaluado('100', '120')
        meta_naranja = self.crear_meta(nombre='Naranja')
        indicador = self.nuevo('100', meta=meta_naranja)
        aporte = self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, indicador=indicador)
        AporteIndicador.objects.filter(pk=aporte.pk).update(valor_validado=Decimal('60'))
        meta_roja = self.crear_meta(nombre='Roja')
        self.nuevo('100', meta=meta_roja, unidad_medida='cantidad', unidad_personalizada='')
        dashboard = self.dashboard()
        self.assertEqual(dashboard['conteos'], dict(verde=1, naranjo=1, rojo=1, sin_datos=1))
        self.assertEqual(dashboard['total_metas'], 4)
        self.assertEqual(dashboard['metas_calculables'], 3)
        self.assertEqual(dashboard['metas_incompletas'], 1)

    def test_lote_y_detalle_dan_los_mismos_resultados(self):
        self.evaluado('40', '120')
        self.evaluado('60', '0')
        lote = calcular_resultados_metas([self.meta_a, self.meta_b])
        for meta in (self.meta_a, self.meta_b):
            self.assertEqual(lote[meta.pk], calcular_resultado_meta(meta))

    def test_consulta_lote_vacio_no_accede_a_base(self):
        with self.assertNumQueries(0):
            self.assertEqual(calcular_resultados_metas([]), {})

    def test_consultas_del_dashboard_no_crecen_por_meta_incluso_con_tiempos(self):
        indicador = self.nuevo('100', unidad_medida='horas', unidad_personalizada='')
        self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, indicador=indicador)
        with CaptureQueriesContext(connection) as iniciales:
            self.respuesta()
        for numero in range(5):
            meta = self.crear_meta(nombre=f'Meta temporal {numero}')
            indicador = self.nuevo('100', meta=meta, unidad_medida='horas', unidad_personalizada='')
            self.vincular('cerrada', AporteIndicador.Estado.CUMPLE, indicador=indicador)
        with CaptureQueriesContext(connection) as ampliadas:
            self.respuesta()
        self.assertEqual(len(iniciales), len(ampliadas))

    def test_consultar_dashboard_no_escribe_datos_ni_auditoria(self):
        self.evaluado('100', '120')
        with CaptureQueriesContext(connection) as consultas:
            self.respuesta()
        escrituras = [q['sql'] for q in consultas if q['sql'].lstrip().split()[0].upper()
                      in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE')]
        self.assertEqual(escrituras, [])

    def test_navegacion_existente_se_conserva(self):
        respuesta = self.respuesta()
        for ruta in ('atenciones:lista', 'agenda:lista', 'evidencias:lista', 'sgr:periodo_lista'):
            self.assertContains(respuesta, f'href="{reverse(ruta)}"')
