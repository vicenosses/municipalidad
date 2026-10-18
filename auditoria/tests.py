from django.test import TestCase

from auditoria.forms import AuditoriaFiltroForm


class AuditoriaFiltroFormTests(TestCase):
    def test_rango_de_fechas_invertido_no_es_valido(self):
        form = AuditoriaFiltroForm(
            data={'fecha_desde': '2026-10-18', 'fecha_hasta': '2026-10-17'}
        )

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_hasta', form.errors)

    def test_fecha_con_formato_invalido_no_es_valida(self):
        form = AuditoriaFiltroForm(data={'fecha_desde': 'ayer'})

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_desde', form.errors)
