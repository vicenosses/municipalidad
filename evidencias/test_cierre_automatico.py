from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image

from atenciones.models import AtencionCiudadana
from evidencias.models import Evidencia
from sgr.test_aportes import DatosAportesMixin


class CierreEvidenciaTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.actividad.estado = AtencionCiudadana.Estado.EN_PROCESO
        self.actividad.save(update_fields=['estado'])

    def evidencia_nueva(self, **extra):
        return Evidencia.objects.create(atencion=self.actividad, subido_por=self.usuarios['funcionario'], archivo='prueba.jpg', **extra)

    def decidir(self, evidencia, accion):
        self.entrar('verificador')
        return self.client.post(reverse('evidencias:validar', args=[evidencia.pk]), {'accion': accion, 'comentario': 'Revisión'})

    def test_aprobacion_cierra_incluso_con_otra_pendiente(self):
        primera = self.evidencia_nueva()
        self.evidencia_nueva()
        self.decidir(primera, 'aprobar')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'cerrada')
        self.assertTrue(self.actividad.historial_estados.filter(estado_nuevo='cerrada').exists())

    def test_rechazo_bloquea_y_reemplazo_aprobado_permite_cierre(self):
        rechazada = self.evidencia_nueva()
        self.decidir(rechazada, 'rechazar')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'en_proceso')
        self.assertFalse(self.actividad.puede_cerrar_por_evidencias())
        reemplazo = self.evidencia_nueva(reemplaza=rechazada)
        self.decidir(reemplazo, 'aprobar')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'cerrada')
        self.assertTrue(Evidencia.objects.filter(pk=rechazada.pk, estado='rechazada').exists())

    def test_rechazo_posterior_reabre(self):
        aprobada = self.evidencia_nueva()
        otra = self.evidencia_nueva()
        self.decidir(aprobada, 'aprobar')
        self.decidir(otra, 'rechazar')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'en_proceso')

    def test_responsable_sube_reemplazo_sin_borrar_original(self):
        rechazada = self.evidencia_nueva()
        self.decidir(rechazada, 'rechazar')
        self.entrar('funcionario')
        datos = BytesIO()
        Image.new('RGB', (2, 2), 'white').save(datos, format='JPEG')
        archivo = SimpleUploadedFile('nueva.jpg', datos.getvalue(), content_type='image/jpeg')
        with TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            respuesta = self.client.post(reverse('evidencias:reemplazar', args=[rechazada.pk]), {'archivos': [archivo]})
            self.assertEqual(respuesta.status_code, 302)
        reemplazo = Evidencia.objects.get(reemplaza=rechazada)
        self.assertEqual(reemplazo.estado, 'pendiente')
        self.assertTrue(Evidencia.objects.filter(pk=rechazada.pk, estado='rechazada').exists())

    def test_rechazo_bloquea_incluso_si_otra_esta_aprobada_hasta_corregir(self):
        aprobada = self.evidencia_nueva(estado='aprobada')
        rechazada = self.evidencia_nueva(estado='rechazada')
        self.assertFalse(self.actividad.puede_cerrar_por_evidencias())
        reemplazo = self.evidencia_nueva(reemplaza=rechazada)
        self.assertFalse(self.actividad.puede_cerrar_por_evidencias())
        self.decidir(reemplazo, 'aprobar')
        self.actividad.refresh_from_db()
        self.assertTrue(self.actividad.puede_cerrar_por_evidencias())
        self.assertEqual(self.actividad.estado, 'cerrada')

    def test_segundo_reemplazo_aprobado_resuelve_cadena_de_rechazos(self):
        primera = self.evidencia_nueva(estado='rechazada')
        segunda = self.evidencia_nueva(estado='rechazada', reemplaza=primera)
        tercera = self.evidencia_nueva(reemplaza=segunda)
        self.assertFalse(self.actividad.puede_cerrar_por_evidencias())
        self.decidir(tercera, 'aprobar')
        self.actividad.refresh_from_db()
        self.assertEqual(self.actividad.estado, 'cerrada')
