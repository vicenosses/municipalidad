from django.db import connection
from django.db.models.functions import Collate
from django.test import TestCase
from django.urls import reverse

from sgr.models import Meta
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class BusquedaMayusculasTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.meta_busqueda = Meta.objects.create(periodo=cls.periodo, delegacion=cls.a,
                                               nombre='ÁRBOLES DEL BARRIO')
        territorio = Territorio.objects.create(nombre='SECTOR ÁLAMO', delegacion=cls.a)
        Vecino.objects.create(rut='12.345.678-5', nombres='MARÍA', apellidos='MUÑOZ', territorio=territorio)

    def test_busca_mayusculas_y_minusculas_incluidos_acentos(self):
        self.assertTrue(Meta.objects.filter(pk=self.meta_busqueda.pk, nombre__icontains='árboles').exists())
        self.entrar('administrador')
        respuesta = self.client.get(reverse('sgr:meta_lista'), {'buscar': 'árboles'})
        self.assertContains(respuesta, self.meta_busqueda.nombre)
        respuesta = self.client.get(reverse('usuarios:territorio_lista'), {'q': 'álamo'})
        self.assertContains(respuesta, 'SECTOR ÁLAMO')
        respuesta = self.client.get(reverse('usuarios:comunidad_lista', args=['vecinos']), {'q': 'maría'})
        self.assertContains(respuesta, 'MARÍA')

    def test_caracteres_comodin_son_literales(self):
        self.assertFalse(Meta.objects.filter(pk=self.meta_busqueda.pk, nombre__icontains='%').exists())
        self.assertFalse(Meta.objects.filter(pk=self.meta_busqueda.pk, nombre__icontains='_').exists())

    def test_mysql_colacion_binaria(self):
        if connection.vendor != 'mysql':
            self.skipTest('La colación binaria se verifica con MySQL o MariaDB.')
        metas = Meta.objects.annotate(nombre_binario=Collate('nombre', 'utf8mb4_bin'))
        self.assertTrue(metas.filter(pk=self.meta_busqueda.pk, nombre_binario__icontains='árboles').exists())
