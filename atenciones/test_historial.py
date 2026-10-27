from django.test import TestCase
from django.urls import reverse

from auditoria.models import RegistroAuditoria
from auditoria.test_base import DatosAuditoriaMixin
from evidencias.models import Evidencia


class HistorialActividadTests(DatosAuditoriaMixin, TestCase):
    def detalle(self, actividad=None):
        return self.client.get(reverse('atenciones:detalle', args=[(actividad or self.actividad_a).pk]))

    def test_eventos_directos_evidencias_y_origen_agenda(self):
        esperados = [self.evento_a.pk]
        for accion in ('cambiar_estado', 'cambiar_va_al_tubo', 'habilitar', 'deshabilitar'):
            esperados.append(self.evento(self.actividad_a, accion=accion).pk)
        evidencia = Evidencia.objects.create(atencion=self.actividad_a, archivo='historia.jpg',
                                             subido_por=self.usuarios['funcionario'])
        for accion in ('crear', 'validar'):
            esperados.append(self.evento(evidencia, accion=accion).pk)
        compromiso = self.compromiso(self.a)
        compromiso.actividades.add(self.actividad_a)
        esperados.append(self.evento(
            compromiso, accion='crear_compromiso_desde_actividad',
            descripcion=f'Compromiso Compromiso creado desde la actividad {self.actividad_a.pk}: Título'
        ).pk)
        interno = self.evento(compromiso, accion='editar', descripcion='Cambio interno privado')
        for rol in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            self.entrar(rol)
            respuesta = self.detalle()
            ids = [r.pk for r in respuesta.context['historial']]
            self.assertEqual(ids, list(reversed(esperados)))
            self.assertNotIn(interno.pk, ids)
            self.assertNotIn(self.evento_b.pk, ids)
            self.assertContains(respuesta, 'Cambio de estado')
            self.assertContains(respuesta, 'Sistema / usuario no disponible')
            self.assertContains(respuesta, 'Validación de evidencia')

    def test_m2m_posterior_no_demuestra_origen_ni_coincidencia_parcial(self):
        compromiso = self.compromiso(self.a)
        compromiso.actividades.add(self.actividad_a, self.actividad_b)
        for origen in (self.actividad_b.pk, f'{self.actividad_a.pk}0'):
            self.evento(compromiso, accion='crear_compromiso_desde_actividad',
                        descripcion=f'Compromiso Compromiso creado desde la actividad {origen}: Otra')
        self.evento(compromiso, accion='crear')
        self.entrar('administrador')
        self.assertEqual([r.pk for r in self.detalle().context['historial']], [self.evento_a.pk])

    def test_historial_vacio(self):
        RegistroAuditoria.objects.filter(pk=self.evento_a.pk).delete()
        self.entrar('funcionario')
        self.assertContains(self.detalle(), 'No hay eventos registrados en el historial de esta actividad.')

    def test_permiso_detalle_protege_historial(self):
        for rol in ('delegado', 'coordinador', 'funcionario', 'verificador'):
            self.entrar(rol)
            respuesta = self.detalle(self.actividad_b)
            self.assertEqual(respuesta.status_code, 404)
            self.assertNotContains(respuesta, self.evento_b.descripcion, status_code=404)
