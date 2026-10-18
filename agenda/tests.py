from django.contrib.auth import get_user_model
from django.test import TestCase

from agenda.forms import CompromisoForm
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


class CompromisoFormTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-1', nombre='Centro')
        self.rol, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.responsable = User.objects.create_user(username='responsable', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.responsable)
        perfil.rol = self.rol
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.otro = User.objects.create_user(username='externo', password='clave-segura')

    def test_responsable_debe_pertenecer_a_la_delegacion(self):
        form = CompromisoForm(
            data={'responsable': self.responsable.pk},
            delegacion=self.delegacion,
        )
        self.assertIn(self.responsable, form.fields['responsable'].queryset)
        self.assertNotIn(self.otro, form.fields['responsable'].queryset)
