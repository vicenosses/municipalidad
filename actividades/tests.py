from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from actividades.models import Actividad
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


class ActividadViewsTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.usuario = User.objects.create_user(username='funcionario', password='clave-segura')
        self.perfil = Perfil.objects.get(usuario=self.usuario)
        self.perfil.rol = self.rol
        self.perfil.delegacion = self.delegacion
        self.perfil.save()
        self.perfil.delegaciones.add(self.delegacion)
        self.client.force_login(self.usuario)

    def test_funcionario_crea_actividad_con_su_usuario_y_delegacion(self):
        respuesta = self.client.post(
            reverse('actividades:crear'),
            {
                'titulo': 'Atención en terreno',
                'descripcion': 'Visita a vecinos de la delegación.',
                'fecha': date.today().isoformat(),
                'estado': Actividad.Estado.REGISTRADA,
            },
        )

        self.assertRedirects(respuesta, reverse('actividades:lista'))
        actividad = Actividad.objects.get()
        self.assertEqual(actividad.funcionario, self.usuario)
        self.assertEqual(actividad.delegacion, self.delegacion)

    def test_creacion_rechaza_campos_obligatorios_vacios(self):
        respuesta = self.client.post(
            reverse('actividades:crear'),
            {'titulo': '', 'descripcion': '', 'fecha': '', 'estado': ''},
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Actividad.objects.exists())

    def test_coordinador_solo_ve_su_delegacion(self):
        otra_delegacion = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        Actividad.objects.create(
            titulo='Actividad local',
            descripcion='Descripción',
            fecha=date.today(),
            funcionario=self.usuario,
            delegacion=self.delegacion,
        )
        Actividad.objects.create(
            titulo='Actividad ajena',
            descripcion='Descripción',
            fecha=date.today(),
            funcionario=self.usuario,
            delegacion=otra_delegacion,
        )
        rol_coordinador, _ = Rol.objects.get_or_create(
            codigo='coordinador',
            defaults={'nombre': 'Coordinador'},
        )
        self.perfil.rol = rol_coordinador
        self.perfil.save()

        respuesta = self.client.get(reverse('actividades:lista'))

        self.assertContains(respuesta, 'Actividad local')
        self.assertNotContains(respuesta, 'Actividad ajena')
