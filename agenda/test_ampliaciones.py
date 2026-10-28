from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Compromiso, SolicitudAmpliacion
from usuarios.models import Delegacion, Rol
from catalogos.models import TipoAtencion, SubAtencion
from atenciones.models import AtencionCiudadana


class AmpliacionesTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(nombre='Centro')
        self.funcionario = self.usuario('funcionario', 'responsable')
        self.verificador = self.usuario('verificador', 'verificador')
        self.compromiso = Compromiso.objects.create(titulo='Prueba', responsable=self.funcionario, delegacion=self.delegacion, fecha_hora=timezone.now() + timedelta(days=3))

    def usuario(self, rol, nombre):
        user = User.objects.create_user(username=nombre, password='Clave123!')
        perfil = user.perfil
        perfil.rol, _ = Rol.objects.get_or_create(codigo=rol, defaults={'nombre': rol})
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        return user

    def test_solicitud_y_aprobacion_por_verificador(self):
        self.client.force_login(self.funcionario)
        plazo = self.compromiso.fecha_hora + timedelta(days=3)
        anterior = self.compromiso.fecha_hora
        respuesta = self.client.post(reverse('agenda:solicitar_ampliacion', args=[self.compromiso.pk]), {'plazo_propuesto': timezone.localtime(plazo).strftime('%Y-%m-%dT%H:%M'), 'motivo': 'Esperamos respuesta'})
        self.assertEqual(respuesta.status_code, 302)
        solicitud = SolicitudAmpliacion.objects.get()
        self.compromiso.refresh_from_db()
        self.assertEqual(self.compromiso.fecha_hora, anterior)
        self.client.force_login(self.verificador)
        self.assertContains(self.client.get(reverse('agenda:ampliaciones')), 'Esperamos respuesta')
        self.client.post(reverse('agenda:decidir_ampliacion', args=[solicitud.pk]), {'accion': 'aprobar'})
        solicitud.refresh_from_db()
        self.compromiso.refresh_from_db()
        self.assertEqual(solicitud.estado, 'aprobada')
        self.assertEqual(self.compromiso.fecha_hora, solicitud.plazo_propuesto)
        self.assertTrue(self.compromiso.historial.filter(campo='fecha_hora').exists())

    def test_fecha_igual_y_funcionario_sin_permiso_de_aprobar(self):
        self.client.force_login(self.funcionario)
        igual = timezone.localtime(self.compromiso.fecha_hora).strftime('%Y-%m-%dT%H:%M')
        respuesta = self.client.post(reverse('agenda:solicitar_ampliacion', args=[self.compromiso.pk]), {'plazo_propuesto': igual, 'motivo': 'Prueba'})
        self.assertEqual(respuesta.status_code, 400)
        self.assertFalse(SolicitudAmpliacion.objects.exists())
        self.assertEqual(self.client.get(reverse('agenda:ampliaciones')).status_code, 403)

    def test_actividad_con_tubo_exige_plazo_y_crea_compromiso(self):
        tipo = TipoAtencion.objects.create(codigo='TIP-PRUEBA', nombre='Tipo')
        sub = SubAtencion.objects.create(nombre='Sub', tipo=tipo)
        self.client.force_login(self.funcionario)
        data = {'titulo': 'Solicitud', 'fecha': timezone.localdate().isoformat(), 'solicitante': 'Vecino', 'tipo': tipo.pk, 'subatencion': sub.pk, 'descripcion': 'Solicitud vecinal', 'va_al_tubo': 'on'}
        respuesta = self.client.post(reverse('atenciones:crear'), data)
        self.assertContains(respuesta, 'Indique el plazo para ingresar al tubo.')
        data['plazo_tubo'] = timezone.localtime(timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        respuesta = self.client.post(reverse('atenciones:crear'), data)
        self.assertEqual(respuesta.status_code, 302)
        actividad = AtencionCiudadana.objects.get(titulo='Solicitud')
        self.assertTrue(actividad.va_al_tubo)
        self.assertEqual(actividad.compromisos.count(), 1)

    def test_rechazo_conserva_plazo_y_otra_delegacion_no_puede_decidir(self):
        anterior = self.compromiso.fecha_hora
        solicitud = SolicitudAmpliacion.objects.create(compromiso=self.compromiso, solicitante=self.funcionario, plazo_anterior=anterior, plazo_propuesto=anterior + timedelta(days=2), motivo='Más tiempo')
        otra = Delegacion.objects.create(nombre='Norte')
        perfil = self.verificador.perfil
        perfil.delegacion = otra
        perfil.save()
        perfil.delegaciones.set([otra])
        self.client.force_login(self.verificador)
        url = reverse('agenda:decidir_ampliacion', args=[solicitud.pk])
        self.assertEqual(self.client.post(url, {'accion': 'aprobar'}).status_code, 404)
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.set([self.delegacion])
        self.client.post(url, {'accion': 'rechazar'})
        solicitud.refresh_from_db()
        self.compromiso.refresh_from_db()
        self.assertEqual(solicitud.estado, 'rechazada')
        self.assertEqual(self.compromiso.fecha_hora, anterior)
