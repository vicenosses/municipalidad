from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sgr.models import AsignacionMeta
from sgr.asignaciones import calcular_resultado_asignacion
from sgr.models import AporteIndicador
from sgr.calculos import calcular_avance_indicador
from sgr.test_aportes import DatosAportesMixin
from sgr.test_metas import DatosMetasMixin


class AsignacionesIndividualesTests(DatosMetasMixin, TestCase):
    def test_misma_meta_admite_distintos_objetivos_por_funcionario(self):
        a = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
                                          cantidad_objetivo=80, ponderacion=20)
        b = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['verificador'],
                                          cantidad_objetivo=90, ponderacion=25)
        self.assertEqual((a.cantidad_objetivo, b.cantidad_objetivo), (80, 90))

    def test_limita_suma_y_rechaza_otra_delegacion(self):
        usuario = self.usuarios['funcionario']
        AsignacionMeta.objects.create(meta=self.meta_a, funcionario=usuario,
                                      cantidad_objetivo=80, ponderacion=70)
        otra = self.crear_meta(nombre='Otra meta')
        with self.assertRaises(ValidationError):
            AsignacionMeta.objects.create(meta=otra, funcionario=usuario,
                                          cantidad_objetivo=5, ponderacion=Decimal('30.01'))
        with self.assertRaises(ValidationError):
            AsignacionMeta.objects.create(meta=self.meta_b, funcionario=usuario,
                                          cantidad_objetivo=5, ponderacion=10)

    def test_asignacion_por_interfaz_y_restriccion_de_acceso(self):
        url = reverse('sgr:asignacion_crear', args=[self.meta_a.pk])
        self.entrar('administrador')
        respuesta = self.client.post(url, {'funcionario': self.usuarios['funcionario'].pk,
            'cantidad_objetivo': '80', 'ponderacion': '20', 'observacion': '', 'activa': 'on'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertTrue(AsignacionMeta.objects.filter(meta=self.meta_a).exists())
        self.entrar('funcionario')
        self.assertIn(self.client.get(url).status_code, (403, 404))


class CalculoAsignacionTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        AsignacionMeta.objects.all().delete()

    def test_solo_se_permite_proponer_meta_asignada(self):
        from sgr.aportes import indicadores_para_actividad
        usuario = self.usuarios['funcionario']
        self.assertFalse(indicadores_para_actividad(self.actividad.fecha, self.a, usuario).exists())
        with self.assertRaises(ValidationError):
            self.asociar()
        asignacion = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=usuario,
                                                   cantidad_objetivo=100, ponderacion=10)
        self.assertIn(self.indicador_a, indicadores_para_actividad(self.actividad.fecha, self.a, usuario))
        self.asociar()
        asignacion.activa = False
        asignacion.save()
        self.assertFalse(indicadores_para_actividad(self.actividad.fecha, self.a, usuario).exists())

    def test_cuenta_aportes_revisados_y_aplica_tope(self):
        asignacion = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
            cantidad_objetivo=Decimal('0.50'), ponderacion=Decimal('25'))
        aporte = AporteIndicador.objects.create(actividad=self.actividad, indicador=self.indicador_a,
                                                estado=AporteIndicador.Estado.PENDIENTE)
        self.assertEqual(calcular_resultado_asignacion(asignacion).cantidad, 0)
        AporteIndicador.objects.filter(pk=aporte.pk).update(estado=AporteIndicador.Estado.CUMPLE)
        resultado = calcular_resultado_asignacion(asignacion)
        self.assertEqual(resultado.cantidad, 1)
        self.assertEqual(resultado.cumplimiento, Decimal('200'))
        self.assertEqual(resultado.cumplimiento_aplicable, Decimal('120'))
        self.assertEqual(resultado.resultado_ponderado, Decimal('30'))

    def test_aprobada_sin_ponderar_se_guarda_y_no_suma(self):
        asignacion = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
            cantidad_objetivo=1, ponderacion=25)
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte, estado=AporteIndicador.Estado.APROBADA_NO_PONDERA,
                     comentario='Es una coordinación previa')
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.APROBADA_NO_PONDERA)
        self.assertEqual(calcular_resultado_asignacion(asignacion).cantidad, 0)
        avance = calcular_avance_indicador(self.indicador_a)
        self.assertEqual(avance.excluidas_no_pondera, 1)
        self.assertEqual(avance.puntos_ponderados, 0)
        self.assertTrue(aporte.historial.filter(accion='aprobar_sin_ponderar').exists())

    def test_anulacion_exige_motivo_y_no_suma(self):
        AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
                                      cantidad_objetivo=3, ponderacion=10)
        aporte = self.asociar()
        self.evidencia()
        with self.assertRaises(ValidationError):
            self.decidir(aporte, estado=AporteIndicador.Estado.ANULADO, comentario='')
        aporte.refresh_from_db()
        self.decidir(aporte, estado=AporteIndicador.Estado.ANULADO, comentario='Registro duplicado de prueba')
        aporte.refresh_from_db()
        self.assertEqual(aporte.estado, AporteIndicador.Estado.ANULADO)
        self.assertEqual(calcular_avance_indicador(self.indicador_a).excluidas_anuladas, 1)
        self.assertEqual(calcular_avance_indicador(self.indicador_a).puntos_ponderados, 0)
        self.assertTrue(aporte.historial.filter(accion='anular_aporte').exists())

    def test_inicio_muestra_solo_asignaciones_propias(self):
        propia = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
                                      cantidad_objetivo=80, ponderacion=20)
        ajena = AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['verificador'],
                                      cantidad_objetivo=90, ponderacion=25)
        self.client.force_login(self.usuarios['funcionario'])
        respuesta = self.client.get(reverse('home'))
        self.assertEqual(respuesta.status_code, 200)
        filas = respuesta.context['metas_individuales']
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]['resultado'].asignacion.funcionario, self.usuarios['funcionario'])
        self.assertEqual(self.client.get(reverse('sgr:mi_asignacion', args=[propia.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('sgr:mi_asignacion', args=[ajena.pk])).status_code, 404)

    def test_revision_positiva_impide_reabrir_o_desactivar(self):
        AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
                                      cantidad_objetivo=100, ponderacion=10)
        aporte = self.asociar()
        self.evidencia()
        self.decidir(aporte, estado=AporteIndicador.Estado.APROBADA_NO_PONDERA,
                     comentario='Se registra sin puntaje')
        from atenciones.permisos import puede_cambiar_estado
        from atenciones.views import puede_cambiar_disponibilidad
        from atenciones.models import AtencionCiudadana
        request = self.request('administrador')
        self.assertFalse(puede_cambiar_estado(request, self.actividad, AtencionCiudadana.Estado.EN_PROCESO))
        self.assertFalse(puede_cambiar_disponibilidad(request, self.actividad))
