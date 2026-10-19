from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from agenda.models import Compromiso
from actividades.models import Actividad
from evidencias.models import Evidencia
from evidencias.forms import EvidenciaForm
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


def crear_imagen(formato='PNG'):
    from PIL import Image

    salida = BytesIO()
    Image.new('RGB', (2, 2), color='red').save(salida, format=formato)
    return salida.getvalue()


class EvidenciaFormTests(TestCase):
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
        self.actividad = Actividad.objects.create(
            titulo='Actividad',
            descripcion='Descripción',
            fecha='2026-10-17',
            funcionario=self.usuario,
            delegacion=self.delegacion,
        )

    def test_acepta_imagen_png_real(self):
        archivo = SimpleUploadedFile(
            'foto.png',
            crear_imagen(),
            content_type='image/png',
        )
        form = EvidenciaForm(
            data={'actividad': self.actividad.pk},
            files={'archivo': archivo},
            user=self.usuario,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_rechaza_contenido_que_no_es_jpg_ni_png(self):
        from PIL import Image

        salida = BytesIO()
        Image.new('RGB', (2, 2), color='red').save(salida, format='GIF')
        archivo = SimpleUploadedFile(
            'foto.gif',
            salida.getvalue(),
            content_type='image/png',
        )
        form = EvidenciaForm(
            data={'actividad': self.actividad.pk},
            files={'archivo': archivo},
            user=self.usuario,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('archivo', form.errors)

    def test_funcionario_no_puede_asociar_actividad_de_otro_funcionario(self):
        otro_usuario = User.objects.create_user(username='otro', password='clave-segura')
        otra_actividad = Actividad.objects.create(
            titulo='Otra actividad',
            descripcion='Descripción',
            fecha='2026-10-17',
            funcionario=otro_usuario,
            delegacion=self.delegacion,
        )
        archivo = SimpleUploadedFile(
            'foto.png',
            crear_imagen(),
            content_type='image/png',
        )
        form = EvidenciaForm(
            data={'actividad': otra_actividad.pk},
            files={'archivo': archivo},
            user=self.usuario,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('actividad', form.errors)

    def test_verificador_no_puede_validar_evidencia_de_otra_delegacion(self):
        otra_delegacion = Delegacion.objects.create(codigo='DEL-2', nombre='Norte')
        otra_actividad = Actividad.objects.create(
            titulo='Actividad ajena',
            descripcion='Descripción',
            fecha='2026-10-17',
            funcionario=self.usuario,
            delegacion=otra_delegacion,
        )
        evidencia = Evidencia.objects.create(
            actividad=otra_actividad,
            archivo='evidencias/prueba.png',
            subido_por=self.usuario,
        )
        rol_verificador, _ = Rol.objects.get_or_create(
            codigo='verificador',
            defaults={'nombre': 'Verificador'},
        )
        self.perfil.rol = rol_verificador
        self.perfil.save()
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('evidencias:validar', args=[evidencia.pk]))

        self.assertEqual(respuesta.status_code, 404)

    def test_filtro_por_origen_distingue_agenda_de_registro(self):
        compromiso = Compromiso.objects.create(
            titulo='Compromiso',
            fecha_hora='2027-01-01T10:00:00Z',
            responsable=self.usuario,
            delegacion=self.delegacion,
        )
        agenda_evidencia = Evidencia.objects.create(
            compromiso=compromiso,
            archivo='evidencias/agenda.png',
            subido_por=self.usuario,
        )
        registro_evidencia = Evidencia.objects.create(
            actividad=self.actividad,
            archivo='evidencias/registro.png',
            subido_por=self.usuario,
        )
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('evidencias:lista'), {'origen': 'agenda'})

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, agenda_evidencia.identificador)
        self.assertNotContains(respuesta, registro_evidencia.identificador)
        detalle = self.client.get(reverse('evidencias:detalle', args=[agenda_evidencia.pk]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'Agenda')
