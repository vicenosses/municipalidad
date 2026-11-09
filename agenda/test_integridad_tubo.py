from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import TipoAtencion, SubAtencion
from usuarios.models import Delegacion, Rol


class IntegridadTuboTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(nombre='Centro prueba tubo')
        self.funcionario = self.crear_usuario('responsable_tubo', 'funcionario')
        self.otro = self.crear_usuario('otro_tubo', 'funcionario')
        self.delegado = self.crear_usuario('delegado_tubo', 'delegado')
        tipo = TipoAtencion.objects.create(codigo='TUB-TEST', nombre='Atención tubo')
        sub = SubAtencion.objects.create(tipo=tipo, nombre='Atención')
        self.actividad = AtencionCiudadana.objects.create(titulo='Actividad propia', fecha=timezone.localdate(),
            solicitante='Vecino', tipo=tipo, subatencion=sub, descripcion='Prueba',
            delegacion=self.delegacion, responsable=self.funcionario, creado_por=self.funcionario, va_al_tubo=True)
        self.compromiso = Compromiso.objects.create(titulo='Seguimiento', fecha_hora=timezone.now()+timedelta(days=3),
            delegacion=self.delegacion, responsable=self.funcionario)
        self.compromiso.actividades.add(self.actividad)

    def crear_usuario(self, nombre, codigo):
        user = User.objects.create_user(username=nombre)
        rol, _ = Rol.objects.get_or_create(codigo=codigo, defaults={'nombre': codigo})
        user.perfil.rol = rol
        user.perfil.delegacion = self.delegacion
        user.perfil.save()
        user.perfil.delegaciones.add(self.delegacion)
        return user

    def test_funcionario_no_puede_ingresar_actividad_ajena(self):
        self.client.force_login(self.otro)
        url = reverse('atenciones:agregar_a_agenda', args=[self.actividad.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        formulario = self.client.get(reverse('agenda:crear')).context['form']
        self.assertNotIn(self.actividad, formulario.fields['actividades'].queryset)
        self.assertNotIn(self.funcionario, formulario.fields['responsable'].queryset)

    def datos_edicion(self):
        return {'titulo': self.compromiso.titulo, 'descripcion': '', 'solicitante': '',
                'rut_solicitante': '', 'telefono_solicitante': '', 'area_apoyo': '',
                'fecha_hora': timezone.localtime(self.compromiso.fecha_hora).strftime('%Y-%m-%dT%H:%M'),
                'responsable': self.funcionario.pk, 'estado': self.compromiso.estado,
                'observaciones': '', 'actividades': []}

    def test_desvincular_ultimo_compromiso_saca_actividad_del_tubo(self):
        self.client.force_login(self.delegado)
        response = self.client.post(reverse('agenda:editar', args=[self.compromiso.pk]), self.datos_edicion())
        self.assertEqual(response.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertFalse(self.actividad.va_al_tubo)
        self.assertTrue(self.compromiso.historial.filter(campo='actividades').exists())

    def test_desvincular_mantiene_en_tubo_si_queda_otro_compromiso(self):
        otro = Compromiso.objects.create(titulo='Otro seguimiento', fecha_hora=timezone.now()+timedelta(days=4),
            delegacion=self.delegacion, responsable=self.funcionario)
        otro.actividades.add(self.actividad)
        self.client.force_login(self.delegado)
        response = self.client.post(reverse('agenda:editar', args=[self.compromiso.pk]), self.datos_edicion())
        self.assertEqual(response.status_code, 302)
        self.actividad.refresh_from_db()
        self.assertTrue(self.actividad.va_al_tubo)
