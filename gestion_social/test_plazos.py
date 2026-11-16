from datetime import date
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from gestion_social.models import GestionSocial
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class PlazosGestionSocialTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        territorio = Territorio.objects.create(nombre='Centro', delegacion=cls.a)
        cls.vecino = Vecino.objects.create(rut='98.765.432-1', nombres='Vecino', apellidos='Prueba', territorio=territorio)

    def datos(self, **extra):
        datos = {'titulo':'Atención vecinal', 'tipo':'orientacion', 'descripcion':'Prueba',
                 'fecha_ingreso':'2026-11-10', 'ingresa_al_tubo':'on', 'vecino':self.vecino.pk}
        datos.update(extra)
        return datos

    def test_pagina_exige_plazo_para_nueva_gestion_en_tubo(self):
        self.entrar('funcionario')
        respuesta = self.client.post(reverse('atenciones:gestion_social:crear'), self.datos())
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Indique un plazo para ingresar la gestión al tubo.')
        self.assertFalse(GestionSocial.objects.exists())
        respuesta = self.client.post(reverse('atenciones:gestion_social:crear'),
                                    self.datos(fecha_compromiso='2026-11-15'))
        self.assertEqual(respuesta.status_code, 302)
        gestion = GestionSocial.objects.get()
        self.assertEqual(gestion.fecha_compromiso, date(2026, 11, 15))

    def test_api_rechaza_plazo_ausente_y_anterior(self):
        from rest_framework.test import APIClient
        cliente = APIClient()
        cliente.force_authenticate(self.usuarios['funcionario'])
        datos = {'titulo':'Gestión', 'tipo':'orientacion', 'descripcion':'Prueba',
                 'fecha_ingreso':'2026-11-10', 'ingresa_al_tubo':True, 'delegacion':self.a.pk, 'vecino':self.vecino.pk}
        respuesta = cliente.post('/api/v1/gestiones-sociales/', datos, format='json')
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('fecha_compromiso', respuesta.data)
        datos['fecha_compromiso'] = '2026-11-09'
        respuesta = cliente.post('/api/v1/gestiones-sociales/', datos, format='json')
        self.assertEqual(respuesta.status_code, 400)
        datos['fecha_compromiso'] = '2026-11-15'
        self.assertEqual(cliente.post('/api/v1/gestiones-sociales/', datos, format='json').status_code, 201)

    def test_modelo_rechaza_ingresar_sin_plazo_y_eliminar_plazo_existente(self):
        gestion = GestionSocial.objects.create(titulo='Caso', descripcion='Prueba', delegacion=self.a,
            responsable=self.usuarios['funcionario'], vecino=self.vecino, fecha_ingreso=date(2026,11,10))
        gestion.ingresa_al_tubo = True
        with self.assertRaises(ValidationError):
            gestion.save()
        gestion.fecha_compromiso = date(2026,11,15)
        gestion.save()
        gestion.fecha_compromiso = None
        with self.assertRaises(ValidationError):
            gestion.save()
        gestion.refresh_from_db()
        self.assertEqual(gestion.fecha_compromiso, date(2026,11,15))

    def test_registro_antiguo_sin_plazo_sigue_editable_y_admite_correccion(self):
        gestion = GestionSocial.objects.create(titulo='Legado', descripcion='Prueba', delegacion=self.a,
            responsable=self.usuarios['funcionario'], vecino=self.vecino, fecha_ingreso=date(2026,11,10))
        GestionSocial.objects.filter(pk=gestion.pk).update(ingresa_al_tubo=True)
        gestion.refresh_from_db()
        gestion.descripcion = 'Actualizado'
        gestion.save()
        self.assertIsNone(gestion.fecha_compromiso)
        gestion.fecha_compromiso = date(2026,11,15)
        gestion.save()
        gestion.fecha_compromiso = None
        with self.assertRaises(ValidationError):
            gestion.save()
