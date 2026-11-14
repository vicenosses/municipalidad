from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from cartas.models import Carta
from gestion_social.models import GestionSocial
from hitos.models import Hito
from operaciones.forms import HitoForm
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class PantallasOperacionesTests(DatosMetasMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.territorio = Territorio.objects.create(
            nombre='Centro', delegacion=cls.a,
        )
        cls.vecino = Vecino.objects.create(
            rut='98.765.432-1',
            nombres='Vecino',
            apellidos='De prueba',
            territorio=cls.territorio,
        )

    def test_secciones_aparecen_dentro_de_actividades_y_agenda(self):
        self.entrar('funcionario')
        actividades = self.client.get(reverse('atenciones:lista'))
        self.assertContains(actividades, reverse('atenciones:gestion_social:lista'))
        agenda = self.client.get(reverse('agenda:lista'))
        self.assertContains(agenda, reverse('agenda:cartas:lista'))
        self.assertContains(agenda, reverse('agenda:hitos:lista'))

    def test_funcionario_registra_gestion_social_en_su_delegacion(self):
        self.entrar('funcionario')
        response = self.client.post(reverse('atenciones:gestion_social:crear'), {
            'titulo': 'Orientación vecinal',
            'tipo': GestionSocial.Tipo.ORIENTACION,
            'descripcion': 'Atención de prueba',
            'fecha_ingreso': '2026-11-10',
            'territorio': self.territorio.pk,
            'vecino': self.vecino.pk,
        })
        self.assertRedirects(response, reverse('atenciones:gestion_social:lista'))
        gestion = GestionSocial.objects.get()
        self.assertEqual(gestion.delegacion, self.a)
        self.assertEqual(gestion.responsable, self.usuarios['funcionario'])
        self.assertEqual(gestion.creado_por, self.usuarios['funcionario'])

    def test_carta_registrada_por_funcionario_es_privada_a_otros_funcionarios(self):
        self.entrar('funcionario')
        response = self.client.post(reverse('agenda:cartas:crear'), {
            'asunto': 'Solicitud vecinal',
            'contenido': 'Contenido confidencial de prueba',
            'fecha_ingreso': '2026-11-10',
            'territorio': self.territorio.pk,
        })
        self.assertRedirects(response, reverse('agenda:cartas:lista'))
        carta = Carta.objects.get()
        self.assertEqual(carta.responsable, self.usuarios['funcionario'])
        self.assertEqual(carta.delegacion, self.a)

        self.entrar('verificador')
        response = self.client.get(reverse('agenda:cartas:detalle', args=[carta.pk]))
        self.assertEqual(response.status_code, 404)

    def test_formularios_y_detalles_de_los_tres_modulos_renderizan(self):
        user = self.usuarios['funcionario']
        carta = Carta.objects.create(
            asunto='Consulta de prueba', contenido='Texto reservado',
            delegacion=self.a, territorio=self.territorio,
            responsable=user, creado_por=user,
        )
        gestion = GestionSocial.objects.create(
            titulo='Caso de prueba', descripcion='Antecedentes reservados',
            delegacion=self.a, territorio=self.territorio,
            vecino=self.vecino,
            responsable=user, creado_por=user,
        )
        compromiso = Compromiso.objects.create(
            titulo='Actividad programada', fecha_hora=timezone.now(),
            responsable=user, delegacion=self.a, creado_por=user,
        )
        hito = Hito.objects.create(
            titulo='Seguimiento', compromiso=compromiso,
            responsable=user, fecha_programada=timezone.localdate(),
            creado_por=user,
        )
        self.entrar('funcionario')

        for ruta in (
            'atenciones:gestion_social:crear',
            'agenda:cartas:crear',
        ):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(reverse(ruta)).status_code, 200)

        detalles = (
            ('atenciones:gestion_social:detalle', gestion, 'Antecedentes reservados'),
            ('agenda:cartas:detalle', carta, 'Texto reservado'),
            ('agenda:hitos:detalle', hito, 'Actividad programada'),
        )
        for ruta, registro, texto in detalles:
            with self.subTest(ruta=ruta):
                self.assertContains(
                    self.client.get(reverse(ruta, args=[registro.pk])),
                    texto,
                )

        self.assertNotContains(
            self.client.get(reverse('agenda:cartas:lista')),
            'Texto reservado',
        )

    def test_solo_administrador_y_delegado_pueden_programar_hito(self):
        self.entrar('administrador')
        self.assertEqual(self.client.get(reverse('agenda:hitos:crear')).status_code, 200)
        self.entrar('delegado')
        self.assertEqual(self.client.get(reverse('agenda:hitos:crear')).status_code, 200)
        self.entrar('coordinador')
        self.assertEqual(self.client.get(reverse('agenda:hitos:crear')).status_code, 403)
        self.entrar('funcionario')
        self.assertEqual(self.client.get(reverse('agenda:hitos:crear')).status_code, 403)

    def test_hito_no_puede_relacionarse_a_nueva_actividad_de_periodo_cerrado(self):
        tipo = TipoAtencion.objects.create(codigo='TIP-HITO', nombre='Tipo hito')
        subatencion = SubAtencion.objects.create(
            codigo='SUB-HITO', nombre='Subatención hito', tipo=tipo,
        )
        actividad_cerrada = AtencionCiudadana.objects.create(
            titulo='Actividad cerrada', fecha='2026-04-10',
            solicitante='Vecino', tipo=tipo, subatencion=subatencion,
            descripcion='Actividad de período cerrado', delegacion=self.a,
            responsable=self.usuarios['administrador'],
        )
        actividad_abierta = AtencionCiudadana.objects.create(
            titulo='Actividad abierta', fecha='2027-04-10',
            solicitante='Vecino', tipo=tipo, subatencion=subatencion,
            descripcion='Actividad de período abierto', delegacion=self.a,
            responsable=self.usuarios['administrador'],
        )
        self.periodo.cerrado = True
        self.periodo.activo = False
        self.periodo.save()
        request = RequestFactory().post('/')
        request.user = self.usuarios['administrador']
        request.session = {'delegacion_activa_id': self.a.pk}

        form = HitoForm(
            data={
                'titulo': 'Hito de seguimiento',
                'actividad': actividad_abierta.pk,
                'actividades': [actividad_cerrada.pk],
                'responsable': self.usuarios['administrador'].pk,
                'fecha_programada': '2027-05-01',
                'periodicidad': Hito.Periodicidad.UNICA,
            },
            request=request,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('actividades', form.errors)
