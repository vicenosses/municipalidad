from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from usuarios.forms import UsuarioEditarForm
from usuarios.models import Cargo, Delegacion, Rol


class CargoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin_cargos', 'admin@example.com', 'ClaveSegura123!')
        self.user = User.objects.create_user('funcionario_cargos', 'funcionario@example.com', 'ClaveSegura123!')
        self.funcionario, _ = Rol.objects.get_or_create(codigo='funcionario', defaults={'nombre': 'Funcionario'})
        self.delegado, _ = Rol.objects.get_or_create(codigo='delegado', defaults={'nombre': 'Delegado'})
        self.delegacion = Delegacion.objects.create(nombre='Delegación cargos')
        self.user.perfil.rol = self.funcionario
        self.user.perfil.delegacion = self.delegacion
        self.user.perfil.save()
        self.user.perfil.delegaciones.add(self.delegacion)
        self.cargo = Cargo.objects.create(nombre='Inspector')

    def datos(self, rol):
        return {'username': self.user.username, 'first_name': 'Nombre', 'last_name': 'Apellido', 'email': self.user.email, 'rol': rol.pk, 'delegaciones': [self.delegacion.pk], 'cargo': self.cargo.pk, 'activo': 'on'}

    def test_cargo_asignable_solo_a_funcionario(self):
        form = UsuarioEditarForm(self.datos(self.funcionario), instance=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.perfil.refresh_from_db()
        self.assertEqual(self.user.perfil.cargo, 'Inspector')
        form = UsuarioEditarForm(self.datos(self.delegado), instance=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn('cargo', form.errors)

    def test_solo_administrador_gestiona_cargos(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('usuarios:cargo_lista')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('usuarios:cargo_crear'), {'nombre': 'Asistente', 'descripcion': 'Atención', 'alcance': 'global', 'activo': 'on'}).status_code, 302)
        self.assertContains(self.client.get(reverse('usuarios:cargo_lista')), 'Asistente')

    def test_editar_y_cambiar_estado_preserva_asignacion(self):
        self.user.perfil.cargo = self.cargo.nombre
        self.user.perfil.save()
        self.client.force_login(self.admin)
        response = self.client.post(reverse('usuarios:cargo_editar', args=[self.cargo.pk]), {'nombre': 'Inspector municipal', 'descripcion': 'Labores de inspección', 'alcance': 'delegacion', 'activo': 'on'})
        self.assertEqual(response.status_code, 302)
        self.user.perfil.refresh_from_db()
        self.assertEqual(self.user.perfil.cargo, 'Inspector municipal')
        self.assertContains(self.client.get(reverse('usuarios:cargo_detalle', args=[self.cargo.pk])), 'Labores de inspección')
        self.client.post(reverse('usuarios:cargo_estado', args=[self.cargo.pk]), {'activo': 'false'})
        self.cargo.refresh_from_db()
        self.assertFalse(self.cargo.activo)
        self.assertContains(self.client.get(reverse('usuarios:cargo_lista')), 'Activar')
        self.client.post(reverse('usuarios:cargo_estado', args=[self.cargo.pk]), {'activo': 'true'})
        self.cargo.refresh_from_db()
        self.assertTrue(self.cargo.activo)

    def test_cargos_inactivos_aparecen_al_final(self):
        inactivo = Cargo.objects.create(nombre='Antes alfabéticamente', activo=False)
        activo = Cargo.objects.create(nombre='Último alfabéticamente')
        self.client.force_login(self.admin)
        cargos = list(self.client.get(reverse('usuarios:cargo_lista')).context['cargos'])
        self.assertLess(cargos.index(activo), cargos.index(inactivo))
