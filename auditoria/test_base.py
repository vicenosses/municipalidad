from django.contrib.auth import get_user_model
from django.utils import timezone

from agenda.models import Compromiso
from atenciones.models import AtencionCiudadana
from auditoria.models import RegistroAuditoria
from catalogos.models import TipoAtencion, SubAtencion
from usuarios.models import Delegacion, Perfil, Rol


class DatosAuditoriaMixin:
    def setUp(self):
        self.a = Delegacion.objects.create(codigo='A8', nombre='Territorio A')
        self.b = Delegacion.objects.create(codigo='B8', nombre='Territorio B')
        self.usuarios = {}
        for codigo in ('administrador', 'delegado', 'coordinador', 'funcionario', 'verificador'):
            usuario = get_user_model().objects.create_user(username=codigo)
            rol, _ = Rol.objects.get_or_create(codigo=codigo, defaults={'nombre': codigo})
            perfil, _ = Perfil.objects.get_or_create(usuario=usuario)
            perfil.rol = rol
            perfil.delegacion = self.a
            perfil.save()
            perfil.delegaciones.set([self.a])
            usuario.refresh_from_db()
            self.usuarios[codigo] = usuario
        self.tipo = TipoAtencion.objects.create(codigo='T8', nombre='Tipo')
        self.sub = SubAtencion.objects.create(nombre='Sub', tipo=self.tipo)
        self.actividad_a = self.actividad(self.a)
        self.actividad_b = self.actividad(self.b)
        self.evento_a = self.evento(self.actividad_a, descripcion='Evento territorial A')
        self.evento_b = self.evento(self.actividad_b, accion='secreto_b',
                                    descripcion='Información exclusiva B',
                                    usuario=self.usuarios['verificador'])

    def actividad(self, delegacion):
        return AtencionCiudadana.objects.create(
            titulo=f'Actividad {delegacion.codigo}', fecha='2026-10-26',
            solicitante='Solicitante', tipo=self.tipo, subatencion=self.sub,
            descripcion='Descripción', delegacion=delegacion,
            responsable=self.usuarios['funcionario'],
        )

    def compromiso(self, delegacion):
        return Compromiso.objects.create(titulo='Compromiso', fecha_hora=timezone.now(),
                                        delegacion=delegacion,
                                        responsable=self.usuarios['coordinador'])

    def evento(self, objeto, accion='crear', descripcion='Evento', usuario=None):
        return RegistroAuditoria.objects.create(
            modelo=objeto._meta.label, objeto_id=str(objeto.pk), accion=accion,
            descripcion=descripcion, usuario=usuario,
        )

    def entrar(self, rol):
        self.client.force_login(self.usuarios[rol])
