from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from atenciones.models import AtencionCiudadana
from sgr.test_aportes import DatosAportesMixin
from usuarios.models import Territorio


class TerritorioActividadTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.local = Territorio.objects.create(nombre='Sector local', delegacion=self.a)
        self.ajeno = Territorio.objects.create(nombre='Sector ajeno', delegacion=self.b)
        self.entrar('funcionario')

    def datos(self, territorio):
        return {'titulo': 'Actividad territorial', 'fecha': timezone.localdate().isoformat(),
                'solicitante': 'Vecino de prueba', 'tipo': self.tipo.pk, 'subatencion': self.sub.pk,
                'descripcion': 'Prueba', 'territorio': territorio.pk}

    def test_crea_y_muestra_territorio_autorizado(self):
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos(self.local))
        self.assertEqual(respuesta.status_code, 302)
        actividad = AtencionCiudadana.objects.get(titulo='Actividad territorial')
        self.assertEqual(actividad.territorio, self.local)
        self.assertContains(self.client.get(reverse('atenciones:detalle', args=[actividad.pk])), self.local.nombre)

    def test_no_acepta_territorio_de_otra_delegacion(self):
        respuesta = self.client.post(reverse('atenciones:crear'), self.datos(self.ajeno))
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn('territorio', respuesta.context['form'].errors)
        self.actividad.territorio = self.ajeno
        with self.assertRaises(ValidationError):
            self.actividad.save()
