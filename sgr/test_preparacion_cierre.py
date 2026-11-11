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
