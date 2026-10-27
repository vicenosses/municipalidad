from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auditoria.models import RegistroAuditoria
from evidencias.models import Evidencia
from evidencias.views import EvidenciaValidarView
from sgr.test_aportes import DatosAportesMixin


class RevisionValidacionEvidenciaTests(DatosAportesMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.evidencia_pendiente = Evidencia.objects.create(atencion=self.actividad,
            subido_por=self.usuarios['funcionario'], archivo='revision/prueba.jpg')
        self.entrar('administrador')

    def validar(self):
        return self.client.post(reverse('evidencias:validar', args=[self.evidencia_pendiente.pk]),
            {'accion': 'rechazar', 'comentario': 'Decisión de la primera solicitud'})

    def test_decision_intercalada_no_se_sobrescribe_con_lectura_pendiente_antigua(self):
        original = EvidenciaValidarView.get_evidencia
        otro = self.usuarios['verificador']

        def obtener_con_intercalado(vista, request, pk):
            evidencia = original(vista, request, pk)
            # Simula otra decisión después de leer y antes de guardar la primera.
            Evidencia.objects.filter(pk=pk).update(estado='aprobada', validado_por=otro,
                fecha_validacion=timezone.now(), comentario_validacion='Decisión ya registrada')
            return evidencia

        with patch.object(EvidenciaValidarView, 'get_evidencia', obtener_con_intercalado):
            self.assertEqual(self.validar().status_code, 302)
        self.evidencia_pendiente.refresh_from_db()
        self.assertEqual(self.evidencia_pendiente.estado, 'aprobada')
        self.assertEqual(self.evidencia_pendiente.validado_por_id, otro.pk)
        self.assertEqual(self.evidencia_pendiente.comentario_validacion, 'Decisión ya registrada')
        self.assertFalse(RegistroAuditoria.objects.filter(accion='validar').exists())

    def test_fallo_de_auditoria_no_deja_decision_sin_trazabilidad(self):
        with patch('evidencias.views.registrar_auditoria', side_effect=RuntimeError('Fallo controlado')):
            with self.assertRaises(RuntimeError):
                self.validar()
        self.evidencia_pendiente.refresh_from_db()
        self.assertEqual(self.evidencia_pendiente.estado, 'pendiente')
        self.assertIsNone(self.evidencia_pendiente.validado_por_id)
