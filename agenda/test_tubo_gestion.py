from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import TipoAtencion, SubAtencion
from gestion_social.models import GestionSocial
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class TuboGestionTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tipo = TipoAtencion.objects.create(codigo='T-GESTION', nombre='Atención de prueba')
        sub = SubAtencion.objects.create(tipo=tipo, nombre='Prueba')
        hoy = timezone.localdate()
        cls.actividad = AtencionCiudadana.objects.create(titulo='Arreglo comunitario', fecha=hoy,
            solicitante='María Muñoz', tipo=tipo, subatencion=sub, descripcion='Prueba',
            delegacion=cls.a, responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'], va_al_tubo=True)
        AtencionCiudadana.objects.create(titulo='Registro de otra delegación', fecha=hoy,
            solicitante='Vecino', tipo=tipo, subatencion=sub, descripcion='Privado', delegacion=cls.b,
            responsable=cls.usuarios['funcionario'], creado_por=cls.usuarios['funcionario'], va_al_tubo=True)
        compromiso = Compromiso.objects.create(titulo='Arreglo comunitario', fecha_hora=timezone.now()-timedelta(days=1),
            rut_solicitante='12.345.678-5', delegacion=cls.a, responsable=cls.usuarios['funcionario'])
        compromiso.actividades.add(cls.actividad)
        territorio = Territorio.objects.create(nombre='Sector A', delegacion=cls.a)
        vecino = Vecino.objects.create(rut='11.111.111-1', nombres='Paula', apellidos='Pérez', territorio=territorio)
        cls.gestion = GestionSocial.objects.create(titulo='Caso social privado', descripcion='Contenido sensible',
            vecino=vecino, delegacion=cls.a, territorio=territorio, responsable=cls.usuarios['funcionario'],
            creado_por=cls.usuarios['funcionario'], ingresa_al_tubo=True, fecha_compromiso=hoy + timedelta(days=4))

    def test_incluye_ambos_tipos_sin_duplicar_y_resguarda_delegacion(self):
        self.entrar('funcionario')
        respuesta = self.client.get(reverse('agenda:tubo'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 2)
        self.assertContains(respuesta, 'Arreglo comunitario', count=1)
        self.assertContains(respuesta, 'Caso social privado')
        self.assertNotContains(respuesta, 'Registro de otra delegación')
        self.assertContains(respuesta, 'Vencido')
        self.assertContains(respuesta, reverse('atenciones:gestion_social:detalle', args=[self.gestion.pk]))

    def test_otra_gestion_solo_muestra_informacion_resumida(self):
        self.entrar('verificador')
        respuesta = self.client.get(reverse('agenda:tubo'))
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 2)
        self.assertContains(respuesta, 'Acceso restringido')
        self.assertNotContains(respuesta, 'Caso social privado')
        self.assertNotContains(respuesta, 'Paula')
        self.assertNotContains(respuesta, reverse('atenciones:gestion_social:detalle', args=[self.gestion.pk]))
        respuesta = self.client.get(reverse('agenda:tubo'), {'q':'111111111'})
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 0)

    def test_busqueda_y_filtros_combinados(self):
        self.entrar('funcionario')
        for consulta in ('MARIA MUNOZ','123456785','arreglo'):
            respuesta = self.client.get(reverse('agenda:tubo'), {'q':consulta,'tipo':'actividad','estado':'vencido'})
            self.assertEqual(respuesta.context['page_obj'].paginator.count, 1)
        respuesta = self.client.get(reverse('agenda:tubo'), {'tipo':'gestion_social','responsable':self.usuarios['funcionario'].perfil.pk})
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 1)
        self.assertContains(respuesta, 'Caso social privado')

    def test_permisos_y_fechas_invalidas(self):
        self.assertEqual(self.client.get(reverse('agenda:tubo')).status_code, 403)
        self.entrar('funcionario')
        respuesta = self.client.get(reverse('agenda:tubo'), {'desde':'2026-12-31','hasta':'2026-01-01'})
        self.assertContains(respuesta, 'La fecha final debe ser igual o posterior')
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 0)


    def test_paginacion_y_filtros_conservan_su_contexto(self):
        for indice in range(26):
            AtencionCiudadana.objects.create(titulo=f'Registro {indice}', fecha=self.actividad.fecha,
                solicitante='Persona', tipo=self.actividad.tipo, subatencion=self.actividad.subatencion,
                descripcion='Prueba', delegacion=self.a, responsable=self.usuarios['funcionario'],
                creado_por=self.usuarios['funcionario'], va_al_tubo=True)
        self.entrar('funcionario')
        respuesta = self.client.get(reverse('agenda:tubo'), {'tipo':'actividad', 'page':2})
        self.assertEqual(respuesta.context['page_obj'].paginator.count, 27)
        self.assertEqual(respuesta.context['page_obj'].number, 2)
        self.assertEqual(len(respuesta.context['filas']), 2)
        self.assertContains(respuesta, 'tipo=actividad')

    def test_administrador_global_ve_otras_delegaciones(self):
        self.entrar('administrador')
        respuesta = self.client.get(reverse('agenda:tubo'))
        self.assertContains(respuesta, 'Registro de otra delegación')
