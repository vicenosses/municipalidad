from django.test import TestCase
from datetime import timedelta
from django.urls import reverse
from django.utils import timezone

from agenda.forms import CompromisoForm
from agenda.models import Compromiso
from sgr.test_metas import DatosMetasMixin


class BusquedaTuboTests(DatosMetasMixin, TestCase):
    def setUp(self):
        self.local = Compromiso.objects.create(titulo='Reparación de camino', solicitante='María Muñoz',
            rut_solicitante='12.345.678-5', fecha_hora=timezone.now(),
            delegacion=self.a, responsable=self.usuarios['funcionario'])
        self.ajeno = Compromiso.objects.create(titulo='Reparación confidencial', solicitante='María Muñoz',
            rut_solicitante='12.345.678-5', fecha_hora=timezone.now(),
            delegacion=self.b, responsable=self.usuarios['funcionario'])
        self.entrar('funcionario')

    def test_busca_nombre_sin_tildes_rut_y_codigo_solo_en_su_delegacion(self):
        for termino in ('MARIA MUNOZ', '123456785', '12.345.678-5', self.local.codigo.lower()):
            with self.subTest(termino=termino):
                response = self.client.get(reverse('agenda:lista'), {'q': termino})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context['compromisos']), [self.local])

    def test_mensaje_sin_resultados_y_busqueda_progresiva(self):
        response = self.client.get(reverse('agenda:lista'), {'q': 'sin coincidencia'})
        self.assertContains(response, 'No hay compromisos que coincidan con la búsqueda.')
        self.assertContains(response, "campo.addEventListener('input'")

    def test_valida_y_normaliza_el_rut(self):
        datos = {'titulo': 'Atención', 'solicitante': 'Vecino', 'fecha_hora': '2027-01-01T10:00',
                 'responsable': self.usuarios['funcionario'].pk, 'estado': 'ingresado',
                 'rut_solicitante': '12345678-5', 'actividades': []}
        form = CompromisoForm(datos, instance=self.local, user=self.usuarios['delegado'], delegaciones=[self.a])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['rut_solicitante'], '12.345.678-5')
        datos['rut_solicitante'] = '12345678-0'
        form = CompromisoForm(datos, instance=self.local, user=self.usuarios['delegado'], delegaciones=[self.a])
        self.assertFalse(form.is_valid())
        self.assertIn('rut_solicitante', form.errors)

    def test_filtro_vencido_combina_busqueda_y_responsable(self):
        self.local.fecha_hora = timezone.now() - timedelta(days=1)
        self.local.save(update_fields=['fecha_hora'])
        respuesta = self.client.get(reverse('agenda:lista'), {'estado': 'vencido', 'q': 'maria',
                                    'responsable': self.usuarios['funcionario'].pk})
        self.assertEqual(list(respuesta.context['compromisos']), [self.local])
        self.local.estado = Compromiso.Estado.REALIZADO
        self.local.save(update_fields=['estado'])
        respuesta = self.client.get(reverse('agenda:lista'), {'estado': 'vencido'})
        self.assertNotIn(self.local, respuesta.context['compromisos'])

    def test_orden_por_fecha_y_titulo(self):
        otro = Compromiso.objects.create(titulo='Actividad inicial', fecha_hora=timezone.now() + timedelta(days=2),
            delegacion=self.a, responsable=self.usuarios['funcionario'])
        respuesta = self.client.get(reverse('agenda:lista'), {'ordenar': 'fecha_desc'})
        self.assertEqual(list(respuesta.context['compromisos']), [otro, self.local])
        respuesta = self.client.get(reverse('agenda:lista'), {'ordenar': 'titulo'})
        self.assertEqual(list(respuesta.context['compromisos']), [otro, self.local])
