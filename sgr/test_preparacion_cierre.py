from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from sgr.models import AsignacionMeta, HistorialCierrePeriodo
from sgr.test_metas import DatosMetasMixin


class PreparacionCierreTests(DatosMetasMixin, TestCase):
    def test_informa_sin_modificar_y_solo_admin_global(self):
        AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['funcionario'],
                                      cantidad_objetivo=80, ponderacion=Decimal('25'))
        self.entrar('administrador')
        respuesta = self.client.get(reverse('sgr:periodo_detalle', args=[self.periodo.pk]))
        self.assertEqual(respuesta.context['revision_cierre']['metas_activas'], 2)
        self.assertEqual(respuesta.context['revision_cierre']['metas_sin_asignacion'], 1)
        self.assertEqual(respuesta.context['revision_cierre']['funcionarios'][0]['ponderacion'], Decimal('25'))
        self.assertContains(respuesta, reverse('sgr:periodo_cerrar', args=[self.periodo.pk]))
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.activo)
        self.entrar('delegado')
        respuesta = self.client.get(reverse('sgr:periodo_detalle', args=[self.periodo.pk]))
        self.assertNotIn('revision_cierre', respuesta.context)

    def test_cierre_congela_datos_y_reapertura_autorizada_conserva_snapshot(self):
        self.entrar('administrador')
        url_cierre = reverse('sgr:periodo_cerrar', args=[self.periodo.pk])
        respuesta = self.client.post(url_cierre, {'motivo': 'Cierre trimestral aprobado'})
        self.assertEqual(respuesta.status_code, 302)
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.cerrado)
        self.assertFalse(self.periodo.activo)
        snapshot = self.periodo.cierre_snapshot
        self.assertEqual(snapshot['periodo']['id'], self.periodo.pk)
        self.assertEqual(HistorialCierrePeriodo.objects.filter(periodo=self.periodo).count(), 1)

        self.meta_a.descripcion = 'Cambio posterior al cierre'
        with self.assertRaises(ValidationError):
            self.meta_a.save()

        url_reapertura = reverse('sgr:periodo_reabrir', args=[self.periodo.pk])
        self.client.post(url_reapertura, {'motivo': 'Reabrir'})
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.cerrado)
        respuesta = self.client.post(
            url_reapertura, {'motivo': 'Reapertura autorizada por resolución'},
        )
        self.assertEqual(respuesta.status_code, 302)
        self.periodo.refresh_from_db()
        self.assertFalse(self.periodo.cerrado)
        self.assertTrue(self.periodo.activo)
        self.assertEqual(self.periodo.cierre_snapshot, snapshot)
        self.assertEqual(
            list(self.periodo.historial_cierre.values_list('accion', flat=True)),
            [HistorialCierrePeriodo.Accion.REABRIR, HistorialCierrePeriodo.Accion.CERRAR],
        )

from django.db import connection
from django.test.utils import CaptureQueriesContext
from sgr.aportes import validar_aporte
from sgr.models import AporteIndicador
from sgr.preparacion_cierre import diagnosticar_periodo
from sgr.test_aportes import DatosAportesMixin


class DiagnosticoCierreDetalladoTests(DatosAportesMixin, TestCase):
    def test_muestra_pendientes_y_metas_sin_asignacion_al_admin_global(self):
        aporte = self.asociar()
        self.entrar('administrador')
        respuesta = self.client.get(reverse('sgr:periodo_detalle', args=[self.periodo.pk]))
        revision = respuesta.context['revision_cierre']
        self.assertEqual(revision['pendientes'], 1)
        self.assertContains(respuesta, aporte.actividad.titulo)
        self.assertContains(respuesta, self.meta_b.nombre)
        self.assertContains(respuesta, 'valores actuales y pueden cambiar')
        self.assertEqual(revision['resultados'][0].cantidad, 0)

    def test_vista_previa_usa_solo_aportes_aprobados_y_no_modifica(self):
        aporte = self.asociar()
        self.evidencia()
        validar_aporte(self.request('verificador'), aporte.pk, aporte.version, AporteIndicador.Estado.CUMPLE)
        revision = diagnosticar_periodo(self.periodo)
        resultado = revision['resultados'][0]
        self.assertEqual(resultado.cantidad, 1)
        self.assertEqual(resultado.cumplimiento_aplicable, Decimal('1'))
        self.assertEqual(resultado.resultado_ponderado, Decimal('0.1'))
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.activo)

    def test_no_ejecuta_una_consulta_por_cada_asignacion(self):
        AsignacionMeta.objects.create(meta=self.meta_a, funcionario=self.usuarios['verificador'],
            cantidad_objetivo=80, ponderacion=10)
        with CaptureQueriesContext(connection) as consultas:
            resultados = diagnosticar_periodo(self.periodo)['resultados']
        self.assertEqual(len(resultados), 2)
        self.assertLessEqual(len(consultas), 7)


class ExportacionRevisionCierreTests(DatosAportesMixin, TestCase):
    def test_excel_muestra_datos_provisionales_y_no_modifica(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.asociar()
        self.entrar('administrador')
        respuesta = self.client.get(reverse('sgr:periodo_revision_exportar', args=[self.periodo.pk]))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('spreadsheetml', respuesta['Content-Type'])
        libro = load_workbook(BytesIO(respuesta.content), data_only=False)
        self.assertIn('PROVISIONAL', libro['Resumen']['B1'].value)
        self.assertEqual(libro['Aportes pendientes'].max_row, 2)
        self.assertEqual(libro['Resultados individuales'].max_row, 2)
        self.assertEqual(libro['Resultados individuales']['D2'].value, 0)
        self.assertEqual(AporteIndicador.objects.count(), 1)

    def test_restringe_descarga_a_admin_en_contexto_global(self):
        url = reverse('sgr:periodo_revision_exportar', args=[self.periodo.pk])
        self.entrar('delegado')
        self.assertEqual(self.client.get(url).status_code, 403)
        self.entrar('administrador')
        sesion = self.client.session
        sesion['delegacion_activa_id'] = self.a.pk
        sesion.save()
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_texto_de_usuario_no_ejecuta_formulas(self):
        from io import BytesIO
        from openpyxl import load_workbook
        self.actividad.titulo = '=1+1'
        self.actividad.save(update_fields=['titulo'])
        self.asociar()
        self.entrar('administrador')
        respuesta = self.client.get(reverse('sgr:periodo_revision_exportar', args=[self.periodo.pk]))
        hoja = load_workbook(BytesIO(respuesta.content))['Aportes pendientes']
        self.assertEqual(hoja['A2'].value, "'=1+1")
        self.assertEqual(hoja['A2'].data_type, 's')
