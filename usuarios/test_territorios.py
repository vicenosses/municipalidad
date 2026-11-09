from django.test import TestCase
from django.urls import reverse

from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio


class TerritoriosTests(DatosMetasMixin, TestCase):
    def test_administrador_crea_y_edita_con_codigo_estable(self):
        self.entrar('administrador')
        respuesta = self.client.post(reverse('usuarios:territorio_crear'),
            {'nombre': 'Centro', 'descripcion': 'Sector céntrico', 'delegacion': self.a.pk, 'activo': 'on'})
        self.assertEqual(respuesta.status_code, 302)
        territorio = Territorio.objects.get(nombre='Centro')
        self.assertTrue(territorio.codigo.startswith('TER-'))
        codigo = territorio.codigo
        respuesta = self.client.post(reverse('usuarios:territorio_editar', args=[territorio.pk]),
            {'nombre': 'Centro Norte', 'descripcion': '', 'delegacion': self.a.pk})
        self.assertEqual(respuesta.status_code, 302)
        territorio.refresh_from_db()
        self.assertEqual(territorio.codigo, codigo)
        self.assertFalse(territorio.activo)

    def test_delegado_consulta_solo_su_delegacion_y_no_puede_crear(self):
        propio = Territorio.objects.create(nombre='Visible', delegacion=self.a)
        Territorio.objects.create(nombre='Exclusivo', delegacion=self.b)
        self.entrar('delegado')
        respuesta = self.client.get(reverse('usuarios:territorio_lista'))
        self.assertContains(respuesta, propio.nombre)
        self.assertNotContains(respuesta, 'Exclusivo')
        self.assertEqual(self.client.get(reverse('usuarios:territorio_crear')).status_code, 403)
