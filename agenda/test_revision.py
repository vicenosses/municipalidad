from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.forms import CompromisoForm
from agenda.models import Compromiso
from atenciones.forms import AtencionCiudadanaForm
from atenciones.models import AtencionCiudadana
from sgr.test_aportes import DatosAportesMixin


class RevisionHistoricasAgendaTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.compromiso = Compromiso.objects.create(titulo='Compromiso local', fecha_hora=timezone.now(),
            delegacion=self.a, responsable=self.usuarios['funcionario'])
        self.local = self.crear_actividad('Histórica local', self.a)
        self.ajena = self.crear_actividad('Histórica exclusiva B', self.b)
        self.compromiso.actividades.add(self.local, self.ajena)

    def crear_actividad(self, titulo, delegacion):
        return AtencionCiudadana.objects.create(titulo=titulo, fecha=self.actividad.fecha,
            solicitante=titulo, tipo=self.tipo, subatencion=self.sub, descripcion='Prueba',
            delegacion=delegacion, responsable=self.usuarios['funcionario'], activo=False)

    def formulario(self, datos=None):
        return CompromisoForm(datos, instance=self.compromiso, user=self.usuarios['delegado'],
                              delegaciones=[self.a])

    def test_opciones_historicas_no_revelan_actividad_deshabilitada_ajena(self):
        opciones = self.formulario().fields['actividades'].queryset
        self.assertIn(self.local, opciones)
        self.assertNotIn(self.ajena, opciones)

    def test_limpieza_conserva_historica_local_sin_incluir_la_ajena(self):
        form = self.formulario({'titulo': 'Compromiso local', 'fecha_hora': '2027-01-01T10:00',
            'responsable': self.usuarios['funcionario'].pk, 'estado': 'ingresado', 'actividades': []})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn(self.local, form.cleaned_data['actividades'])
        self.assertNotIn(self.ajena, form.cleaned_data['actividades'])
        self.assertEqual(self.compromiso.delegacion_id, self.a.pk)

    def test_post_no_acepta_historica_ajena_por_id(self):
        form = self.formulario({'titulo': 'Compromiso local', 'fecha_hora': '2027-01-01T10:00',
            'responsable': self.usuarios['funcionario'].pk, 'estado': 'ingresado', 'actividades': [self.ajena.pk]})
        self.assertFalse(form.is_valid())
        self.assertIn('actividades', form.errors)

    def test_vista_de_edicion_no_muestra_titulo_de_actividad_ajena(self):
        self.entrar('delegado')
        respuesta = self.client.get(reverse('agenda:editar', args=[self.compromiso.pk]))
        self.assertContains(respuesta, self.local.titulo)
        self.assertNotContains(respuesta, self.ajena.titulo)


class RevisionIdentificadoresActividadTests(DatosAportesMixin, TestCase):
    def test_tipo_malformado_es_error_de_formulario_y_no_excepcion(self):
        for tipo in ('texto', '1.5', ''):
            with self.subTest(tipo=tipo):
                form = AtencionCiudadanaForm(self.datos_actividad(tipo=tipo), request=self.request())
                self.assertFalse(form.is_valid())
                self.assertIn('tipo', form.errors)

    def test_post_tipo_malformado_no_crea_registro_y_responde_con_formulario(self):
        self.entrar('funcionario')
        antes = AtencionCiudadana.objects.count()
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos_actividad(tipo='texto'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('tipo', respuesta.context['form'].errors)
        self.assertEqual(AtencionCiudadana.objects.count(), antes)
