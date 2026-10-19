from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from agenda.forms import CompromisoForm
from agenda.models import Compromiso, HistorialCompromiso
from actividades.models import Actividad
from evidencias.models import Evidencia
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

    def test_no_permite_saltar_transiciones_de_estado(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso de prueba',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        form = CompromisoForm(
            data={
                'titulo': compromiso.titulo,
                'descripcion': '',
                'solicitante': '',
                'area_apoyo': '',
                'fecha_hora': '2027-01-01T10:00',
                'responsable': self.responsable.pk,
                'estado': Compromiso.Estado.REALIZADO,
                'observaciones': '',
                'actividades': [],
            },
            instance=compromiso,
            user=self.responsable,
            delegaciones=[self.delegacion],
        )
        self.assertFalse(form.is_valid(), form.cleaned_data)
        self.assertIn('estado', form.errors)


class AgendaWorkflowTests(TestCase):
    def setUp(self):
        self.delegacion = Delegacion.objects.create(codigo='DEL-COORD', nombre='Centro')
        self.rol_coordinador, _ = Rol.objects.get_or_create(
            codigo='coordinador',
            defaults={'nombre': 'Coordinador'},
        )
        self.coordinador = User.objects.create_user(username='coord', password='clave-segura')
        rol_funcionario, _ = Rol.objects.get_or_create(
            codigo='funcionario',
            defaults={'nombre': 'Funcionario'},
        )
        self.responsable = User.objects.create_user(username='func', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.responsable)
        perfil.rol = rol_funcionario
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        perfil = self.coordinador.perfil
        perfil.rol = self.rol_coordinador
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.assertEqual(perfil.rol_codigo, 'coordinador')

    def test_edicion_audita_transiciones_y_registra_fecha_realizacion(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
            estado=Compromiso.Estado.INGRESADO,
        )
        self.client.force_login(self.coordinador)

        datos = {
            'titulo': compromiso.titulo,
            'descripcion': '',
            'solicitante': '',
            'area_apoyo': '',
            'fecha_hora': '2027-01-01T10:00',
            'responsable': self.responsable.pk,
            'observaciones': '',
            'actividades': [],
            'motivo_cambio': '',
        }
        for estado in (
            Compromiso.Estado.PENDIENTE,
            Compromiso.Estado.EN_PROCESO,
            Compromiso.Estado.REALIZADO,
        ):
            datos['estado'] = estado
            respuesta = self.client.post(reverse('agenda:editar', args=[compromiso.pk]), datos)
            self.assertEqual(respuesta.status_code, 302)
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.estado, Compromiso.Estado.REALIZADO)
        self.assertIsNotNone(compromiso.fecha_realizacion)
        self.assertEqual(
            HistorialCompromiso.objects.filter(
                compromiso=compromiso,
                campo='estado',
                realizado_por=self.coordinador,
            ).count(),
            3,
        )

    def test_reasignar_requiere_motivo(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        nuevo_responsable = User.objects.create_user(username='func2', password='clave-segura')
        perfil = Perfil.objects.get(usuario=nuevo_responsable)
        perfil.rol = self.responsable.perfil.rol
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        datos = {
            'titulo': compromiso.titulo,
            'descripcion': '',
            'solicitante': '',
            'area_apoyo': '',
            'fecha_hora': '2027-01-01T10:00',
            'responsable': nuevo_responsable.pk,
            'estado': Compromiso.Estado.INGRESADO,
            'observaciones': '',
            'actividades': [],
            'motivo_cambio': '',
        }
        form = CompromisoForm(
            data=datos,
            instance=compromiso,
            user=self.coordinador,
            delegaciones=[self.delegacion],
        )

        self.assertEqual(self.coordinador.perfil.rol_codigo, 'coordinador')
        self.assertNotEqual(nuevo_responsable.pk, compromiso.responsable_id)
        self.assertFalse(form.is_valid(), form.cleaned_data)
        self.assertIn('motivo_cambio', form.errors)
        datos['motivo_cambio'] = 'Reasignación por ausencia del responsable original'
        form = CompromisoForm(
            data=datos,
            instance=compromiso,
            user=self.coordinador,
            delegaciones=[self.delegacion],
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.client.force_login(self.coordinador)
        respuesta = self.client.post(
            reverse('agenda:editar', args=[compromiso.pk]),
            datos,
        )
        self.assertEqual(respuesta.status_code, 302)
        cambio = HistorialCompromiso.objects.get(
            compromiso=compromiso,
            campo='responsable',
        )
        self.assertEqual(cambio.motivo, datos['motivo_cambio'])
        compromiso.refresh_from_db()
        self.assertEqual(compromiso.responsable, nuevo_responsable)

    def test_evidencia_de_agenda_solo_la_sube_el_responsable_o_jefatura(self):
        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        actividad = Actividad.objects.create(
            titulo='Preparación',
            descripcion='Preparación del evento',
            fecha='2026-10-20',
            funcionario=self.responsable,
            delegacion=self.delegacion,
        )
        compromiso.actividades.add(actividad)
        self.client.force_login(self.responsable)

        respuesta = self.client.get(reverse('agenda:detalle', args=[compromiso.pk]))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Preparación')
        self.assertContains(respuesta, 'Adjuntar evidencia')
        self.assertFalse(Evidencia.objects.filter(compromiso=compromiso).exists())

    def test_responsable_adjunto_archivo_con_origen_agenda(self):
        from PIL import Image

        compromiso = Compromiso.objects.create(
            titulo='Jornada vecinal',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.responsable,
            delegacion=self.delegacion,
        )
        contenido = BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(contenido, format='PNG')
        archivo = SimpleUploadedFile('respaldo.png', contenido.getvalue(), content_type='image/png')
        self.client.force_login(self.responsable)

        respuesta = self.client.post(
            reverse('evidencias:agenda_crear', args=[compromiso.pk]),
            {'descripcion': 'Registro fotográfico', 'archivos': [archivo]},
        )

        self.assertRedirects(respuesta, reverse('agenda:detalle', args=[compromiso.pk]))
        evidencia = Evidencia.objects.get(compromiso=compromiso)
        self.assertEqual(evidencia.descripcion, 'Registro fotográfico')
        self.assertEqual(evidencia.origen, 'Agenda')
