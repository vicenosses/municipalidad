import shutil
import struct
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from atenciones.models import AtencionCiudadana
from catalogos.models import SubAtencion, TipoAtencion
from evidencias.forms import EvidenciaAtencionForm
from evidencias.models import Evidencia
from usuarios.models import Delegacion, Perfil, Rol

User = get_user_model()


def imagen_valida(extension='png', formato='PNG'):
    contenido = BytesIO()
    Image.new('RGB', (3, 3), color='red').save(contenido, format=formato)
    return SimpleUploadedFile(
        f'evidencia.{extension}',
        contenido.getvalue(),
        content_type=f'image/{extension if extension != "jpg" else "jpeg"}',
    )


def mp4_valido():
    contenido = (
        struct.pack('>I4s4sI', 16, b'ftyp', b'isom', 0)
        + struct.pack('>I4s', 8, b'moov')
        + struct.pack('>I4s', 9, b'mdat')
        + b'\x00'
    )
    return SimpleUploadedFile('clip.mp4', contenido, content_type='video/mp4')


def webm_valido():
    contenido = (
        b'\x1a\x45\xdf\xa3'
        b'\x42\x82\x84webm'
        b'\x18\x53\x80\x67'
        b'\x16\x54\xae\x6b'
        b'\x1f\x43\xb6\x75'
    )
    return SimpleUploadedFile('clip.webm', contenido, content_type='video/webm')


class EvidenciaAtencionTests(TestCase):
    def setUp(self):
        self.directorio_media = tempfile.mkdtemp(prefix='sgr-test-media-')
        self.override_media = override_settings(MEDIA_ROOT=self.directorio_media)
        self.override_media.enable()
        self.addCleanup(self.override_media.disable)
        self.addCleanup(shutil.rmtree, self.directorio_media, ignore_errors=True)

        self.delegacion = Delegacion.objects.create(codigo='TEST-1', nombre='Delegación de prueba')
        self.tipo = TipoAtencion.objects.create(codigo='TEST-T', nombre='Tipo de prueba')
        self.subtipo = SubAtencion.objects.create(
            codigo='TEST-S',
            nombre='Subatención de prueba',
            tipo=self.tipo,
        )
        self.creador = User.objects.create_user(username='vicente.test', password='clave-segura')
        perfil = Perfil.objects.get(usuario=self.creador)
        perfil.delegacion = self.delegacion
        perfil.save(update_fields=['delegacion'])
        perfil.delegaciones.add(self.delegacion)
        self.atencion = AtencionCiudadana.objects.create(
            solicitante='Persona de prueba',
            tipo=self.tipo,
            subatencion=self.subtipo,
            descripcion='Atención de prueba',
            delegacion=self.delegacion,
            responsable=self.creador,
        )
        self.client.force_login(self.creador)

    def test_listado_muestra_acciones_juntas_y_solo_al_creador(self):
        respuesta = self.client.get(reverse('atenciones:lista'))

        self.assertContains(respuesta, reverse('atenciones:detalle', args=[self.atencion.pk]))
        self.assertContains(respuesta, reverse('evidencias:atencion_crear', args=[self.atencion.pk]))
        html = respuesta.content.decode()
        self.assertLess(html.index('>Ver</a>'), html.index('>Agregar evidencia</a>'))

        otro = User.objects.create_user(username='otro.usuario', password='clave-segura')
        perfil_otro = Perfil.objects.get(usuario=otro)
        perfil_otro.rol = Rol.objects.get(codigo='coordinador')
        perfil_otro.delegacion = self.delegacion
        perfil_otro.save()
        perfil_otro.delegaciones.add(self.delegacion)
        self.client.force_login(otro)
        respuesta_otro = self.client.get(reverse('atenciones:lista'))
        self.assertContains(respuesta_otro, self.atencion.solicitante)
        self.assertNotContains(respuesta_otro, 'Agregar evidencia')

    def test_creador_puede_subir_imagen_y_video_en_el_mismo_envio(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {
                'archivos': [
                    imagen_valida(),
                    imagen_valida('jpg', 'JPEG'),
                    imagen_valida('webp', 'WEBP'),
                    mp4_valido(),
                ]
            },
        )

        self.assertRedirects(respuesta, reverse('atenciones:detalle', args=[self.atencion.pk]))
        evidencias = list(Evidencia.objects.filter(atencion=self.atencion).order_by('tipo_archivo'))
        self.assertEqual(len(evidencias), 4)
        self.assertEqual({e.tipo_archivo for e in evidencias}, {'imagen', 'video'})
        self.assertTrue(all(e.estado == Evidencia.Estado.PENDIENTE for e in evidencias))
        self.assertTrue(all(e.subido_por == self.creador for e in evidencias))
        self.assertEqual(len({e.identificador for e in evidencias}), 4)
        prefijo = f'{timezone.localtime().strftime("%Y%m%d")}_vicentetest_'
        self.assertTrue(all(e.identificador.startswith(prefijo) for e in evidencias))

    def test_creador_puede_subir_video_webm(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {'archivos': [webm_valido()]},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(Evidencia.objects.get().tipo_archivo, 'video')

    def test_otro_usuario_no_puede_abrir_formulario_ni_enviar_archivos(self):
        otro = User.objects.create_user(username='otro.usuario', password='clave-segura')
        self.client.force_login(otro)
        url = reverse('evidencias:atencion_crear', args=[self.atencion.pk])

        self.assertEqual(self.client.get(url).status_code, 404)
        respuesta = self.client.post(url, {'archivos': [imagen_valida()]})
        self.assertEqual(respuesta.status_code, 404)
        self.assertFalse(Evidencia.objects.exists())

    def test_archivos_invalidos_y_demasiado_grandes_se_rechazan(self):
        archivo_falso = SimpleUploadedFile(
            'falso.png',
            b'no es una imagen',
            content_type='image/png',
        )
        form_falso = EvidenciaAtencionForm(files={'archivos': [archivo_falso]})
        self.assertFalse(form_falso.is_valid())

        tipo_falso = SimpleUploadedFile(
            'foto.txt',
            b'contenido',
            content_type='image/png',
        )
        form_tipo = EvidenciaAtencionForm(files={'archivos': [tipo_falso]})
        self.assertFalse(form_tipo.is_valid())

        with override_settings(EVIDENCIA_MAX_IMAGE_MB=0):
            form_grande = EvidenciaAtencionForm(files={'archivos': [imagen_valida()]})
            self.assertFalse(form_grande.is_valid())

        with override_settings(EVIDENCIA_MAX_BATCH_MB=0):
            form_lote = EvidenciaAtencionForm(files={'archivos': [imagen_valida()]})
            self.assertFalse(form_lote.is_valid())

    def test_estado_general_prioriza_rechazado_y_luego_pendiente(self):
        self.assertEqual(self.atencion.estado_evidencias, 'sin_evidencia')
        primera = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/imagen.png',
            subido_por=self.creador,
            estado=Evidencia.Estado.APROBADA,
        )
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'aprobada')
        segunda = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'pendiente')
        segunda.estado = Evidencia.Estado.RECHAZADA
        segunda.save(update_fields=['estado'])
        self.atencion.refresh_from_db()
        self.assertEqual(self.atencion.estado_evidencias, 'rechazada')
        self.assertEqual(primera.estado, Evidencia.Estado.APROBADA)

    def test_administrador_puede_aprobar_y_rechazar_y_cambios_se_reflejan(self):
        aprobado = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/aprobada.png',
            subido_por=self.creador,
        )
        rechazada = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/rechazada.png',
            subido_por=self.creador,
        )
        administrador = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='clave-segura',
        )
        self.client.force_login(administrador)
        lista_admin = self.client.get(reverse('evidencias:lista'))
        self.assertContains(lista_admin, aprobado.identificador)
        self.assertContains(lista_admin, rechazada.identificador)

        self.client.post(
            reverse('evidencias:validar', args=[aprobado.pk]),
            {'accion': 'aprobar', 'comentario': ''},
        )
        self.client.post(
            reverse('evidencias:validar', args=[rechazada.pk]),
            {'accion': 'rechazar', 'comentario': 'Falta contexto'},
        )
        aprobado.refresh_from_db()
        rechazada.refresh_from_db()
        self.atencion.refresh_from_db()

        self.assertEqual(aprobado.estado, Evidencia.Estado.APROBADA)
        self.assertEqual(rechazada.estado, Evidencia.Estado.RECHAZADA)
        self.assertEqual(rechazada.comentario_validacion, 'Falta contexto')
        self.assertEqual(self.atencion.estado_evidencias, 'rechazada')
        detalle = self.client.get(reverse('atenciones:detalle', args=[self.atencion.pk]))
        self.assertContains(detalle, 'Falta contexto')
        self.assertContains(detalle, 'Rechazada')

    def test_archivo_privado_no_se_sirve_a_otro_usuario(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/privada.png',
            subido_por=self.creador,
        )
        otro = User.objects.create_user(username='visitante', password='clave-segura')
        self.client.force_login(otro)

        respuesta = self.client.get(reverse('evidencia_archivo', args=[evidencia.pk]))

        self.assertEqual(respuesta.status_code, 404)

    def test_coordinador_no_puede_revisar_evidencia_ciudadana(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        coordinador = User.objects.create_user(username='coordinador', password='clave-segura')
        perfil = Perfil.objects.get(usuario=coordinador)
        perfil.rol = Rol.objects.get(codigo='coordinador')
        perfil.delegacion = self.delegacion
        perfil.save()
        perfil.delegaciones.add(self.delegacion)
        self.client.force_login(coordinador)

        respuesta = self.client.post(
            reverse('evidencias:validar', args=[evidencia.pk]),
            {'accion': 'aprobar', 'comentario': ''},
        )

        evidencia.refresh_from_db()
        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(evidencia.estado, Evidencia.Estado.PENDIENTE)

    def test_archivo_no_se_expone_por_su_ruta_fisica_de_media(self):
        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/privada.png',
            subido_por=self.creador,
        )

        respuesta = self.client.get(f'/media/{evidencia.archivo.name}')

        self.assertEqual(respuesta.status_code, 404)

    def test_detalle_muestra_todas_las_evidencias_del_creador(self):
        for nombre in ('uno.png', 'dos.mp4'):
            Evidencia.objects.create(
                atencion=self.atencion,
                archivo=f'evidencias/{nombre}',
                subido_por=self.creador,
            )

        respuesta = self.client.get(reverse('atenciones:detalle', args=[self.atencion.pk]))

        prefijo = f'{timezone.localtime().strftime("%Y%m%d")}_vicentetest_'
        self.assertContains(respuesta, f'{prefijo}imagen_')
        self.assertContains(respuesta, f'{prefijo}video_')
        self.assertContains(respuesta, '<video', html=False)
        self.assertContains(respuesta, '<img', html=False)
        self.assertEqual(respuesta.context['evidencias'].count(), 2)

    def test_estado_del_listado_usa_paneles_de_color_por_prioridad(self):
        lista = reverse('atenciones:lista')
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Sin evidencia')
        self.assertContains(respuesta, 'bg-light text-secondary border')

        evidencia = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/aprobada.png',
            subido_por=self.creador,
            estado=Evidencia.Estado.APROBADA,
        )
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Aprobada')
        self.assertContains(respuesta, 'bg-success text-white')

        evidencia_pendiente = Evidencia.objects.create(
            atencion=self.atencion,
            archivo='evidencias/pendiente.png',
            subido_por=self.creador,
        )
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Pendiente')
        self.assertContains(respuesta, 'bg-secondary text-white')

        evidencia_pendiente.estado = Evidencia.Estado.RECHAZADA
        evidencia_pendiente.save(update_fields=['estado'])
        respuesta = self.client.get(lista)
        self.assertContains(respuesta, 'Rechazada')
        self.assertContains(respuesta, 'bg-danger text-white')

    def test_propietario_puede_ver_archivo_y_mime_de_servido_es_seguro(self):
        respuesta = self.client.post(
            reverse('evidencias:atencion_crear', args=[self.atencion.pk]),
            {'archivos': [imagen_valida()]},
        )
        self.assertEqual(respuesta.status_code, 302)
        evidencia = Evidencia.objects.get()

        archivo = self.client.get(reverse('evidencia_archivo', args=[evidencia.pk]))

        self.assertEqual(archivo.status_code, 200)
        self.assertEqual(archivo['Content-Type'], 'image/png')
        self.assertEqual(archivo['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', archivo['Cache-Control'])
