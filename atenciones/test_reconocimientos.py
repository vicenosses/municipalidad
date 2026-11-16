from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from atenciones.models import ReconocimientoCiudadano
from auditoria.models import RegistroAuditoria
from sgr.test_metas import DatosMetasMixin
from usuarios.models import Territorio, Vecino


class ReconocimientosCiudadanosTests(DatosMetasMixin, TestCase):
    def datos(self, **extra):
        datos = {
            'tipo': ReconocimientoCiudadano.Tipo.RECLAMO,
            'titulo': 'Solicitud de iluminación',
            'descripcion': 'Dato ficticio de prueba',
            'fecha': '2026-05-10',
        }
        datos.update(extra)
        return datos

    def test_funcionario_crea_registro_con_codigo_y_auditoria(self):
        self.entrar('funcionario')

        respuesta = self.client.post(
            reverse('atenciones:reconocimientos:crear'), self.datos(),
        )

        self.assertRedirects(respuesta, reverse('atenciones:reconocimientos:lista'))
        registro = ReconocimientoCiudadano.objects.get()
        self.assertTrue(registro.codigo.startswith('RCF-'))
        self.assertEqual(registro.responsable, self.usuarios['funcionario'])
        self.assertEqual(registro.delegacion, self.a)
        self.assertEqual(registro.creado_por, self.usuarios['funcionario'])
        self.assertTrue(RegistroAuditoria.objects.filter(
            modelo='atenciones.ReconocimientoCiudadano',
            objeto_id=str(registro.pk),
            accion='crear_reconocimiento_ciudadano',
        ).exists())

    def test_lista_respeta_delegacion_y_funcionario(self):
        self.usuarios['funcionario'].perfil.delegaciones.add(self.b)
        local = ReconocimientoCiudadano.objects.create(
            tipo=ReconocimientoCiudadano.Tipo.FELICITACION,
            titulo='Buen servicio', fecha='2026-05-11',
            delegacion=self.a, responsable=self.usuarios['funcionario'],
            creado_por=self.usuarios['funcionario'],
        )
        ReconocimientoCiudadano.objects.create(
            tipo=ReconocimientoCiudadano.Tipo.RECLAMO,
            titulo='Caso de otra delegación', fecha='2026-05-11',
            delegacion=self.b, responsable=self.usuarios['funcionario'],
            creado_por=self.usuarios['funcionario'],
        )
        self.entrar('funcionario')

        respuesta = self.client.get(reverse('atenciones:reconocimientos:lista'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, local.titulo)
        self.assertNotContains(respuesta, 'Caso de otra delegación')

    def test_vecino_y_territorio_de_delegaciones_distintas_se_rechazan(self):
        territorio_a = Territorio.objects.create(nombre='Centro', delegacion=self.a)
        vecino = Vecino.objects.create(
            rut='98.765.432-1', nombres='Vecino', apellidos='Prueba',
            territorio=territorio_a,
        )
        with self.assertRaises(ValidationError):
            ReconocimientoCiudadano.objects.create(
                tipo=ReconocimientoCiudadano.Tipo.RECLAMO,
                titulo='Registro inconsistente', fecha='2026-05-11',
                vecino=vecino, delegacion=self.b, territorio=territorio_a,
                responsable=self.usuarios['funcionario'],
            )
