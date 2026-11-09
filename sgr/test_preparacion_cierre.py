from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from sgr.models import AsignacionMeta
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
        self.assertContains(respuesta, 'el congelamiento de resultados aún no están habilitados')
        self.periodo.refresh_from_db()
        self.assertTrue(self.periodo.activo)
        self.entrar('delegado')
        respuesta = self.client.get(reverse('sgr:periodo_detalle', args=[self.periodo.pk]))
        self.assertNotIn('revision_cierre', respuesta.context)
