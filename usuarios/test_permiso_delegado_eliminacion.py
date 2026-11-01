from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from catalogos.models import TipoAtencion, SubAtencion
from usuarios.models import Delegacion, Rol
from atenciones.models import AtencionCiudadana, HistorialEstadoActividad
from django.utils import timezone


class DelegadoYEliminacionTests(TestCase):
    def setUp(self):
        self.a = Delegacion.objects.create(nombre='Delegación A')
        self.b = Delegacion.objects.create(nombre='Delegación B')
        self.delegado = User.objects.create_user('delegado_prueba', password='Password123!')
        perfil = self.delegado.perfil
        perfil.rol = Rol.objects.get(codigo='delegado')
        perfil.delegacion = self.a
        perfil.save()
        perfil.delegaciones.add(self.a)
        self.admin = User.objects.create_superuser('admin_prueba', 'admin@example.com', 'Password123!')

    def datos(self, rol, delegacion):
        return {'username': 'creado', 'first_name': 'Persona', 'last_name': 'Prueba', 'email': 'creado@example.com', 'password1': 'ContraseñaSegura123!', 'password2': 'ContraseñaSegura123!', 'rol': rol.pk, 'delegaciones': [delegacion.pk], 'activo': 'on'}

    def test_delegado_solo_crea_roles_inferiores_en_su_delegacion(self):
        self.client.force_login(self.delegado)
        url = reverse('usuarios:crear')
        for rol, delegacion in [(Rol.objects.get(codigo='administrador'), self.a), (Rol.objects.get(codigo='delegado'), self.a), (Rol.objects.get(codigo='funcionario'), self.b)]:
            respuesta = self.client.post(url, self.datos(rol, delegacion))
            self.assertEqual(respuesta.status_code, 200)
            self.assertFalse(User.objects.filter(username='creado').exists())
        respuesta = self.client.post(url, self.datos(Rol.objects.get(codigo='coordinador'), self.a))
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(list(User.objects.get(username='creado').perfil.delegaciones.all()), [self.a])

    def test_eliminar_solo_admin_y_bloquea_registros_relacionados(self):
        tipo = TipoAtencion.objects.create(codigo='BORRAR', nombre='Tipo prueba')
        url = reverse('eliminar_registro', args=['tipo', tipo.pk])
        self.client.force_login(self.delegado)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        SubAtencion.objects.create(tipo=tipo, nombre='Sub vinculada')
        self.client.post(url)
        self.assertTrue(TipoAtencion.objects.filter(pk=tipo.pk).exists())
        tipo.subatenciones.all().delete()
        self.client.post(url)
        self.assertFalse(TipoAtencion.objects.filter(pk=tipo.pk).exists())

    def test_sesion_cerrada_no_accede_a_paginas_privadas(self):
        self.client.force_login(self.admin)
        respuesta = self.client.get(reverse('home'))
        self.assertIn('no-store', respuesta['Cache-Control'])
        self.client.post(reverse('logout'))
        respuesta = self.client.get(reverse('home'))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('login'), respuesta.url)

    def test_elimina_actividad_sin_relaciones_y_registra_auditoria(self):
        from auditoria.models import RegistroAuditoria
        tipo = TipoAtencion.objects.create(codigo='EL-ACT', nombre='Tipo actividad')
        sub = SubAtencion.objects.create(tipo=tipo, nombre='Sub actividad')
        actividad = AtencionCiudadana.objects.create(titulo='Borrar', fecha=timezone.localdate(), solicitante='Vecino', tipo=tipo, subatencion=sub, descripcion='Prueba', delegacion=self.a, responsable=self.delegado)
        HistorialEstadoActividad.objects.create(actividad=actividad, estado_nuevo='registrada')
        pk = actividad.pk
        self.client.force_login(self.admin)
        self.client.post(reverse('eliminar_registro', args=['actividad', pk]))
        self.assertFalse(AtencionCiudadana.objects.filter(pk=pk).exists())
        self.assertTrue(RegistroAuditoria.objects.filter(accion='eliminar', modelo='atenciones.AtencionCiudadana', objeto_id=str(pk)).exists())
