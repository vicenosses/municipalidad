from django.test import TestCase

from auditoria.forms import AuditoriaFiltroForm
from auditoria.test_base import DatosAuditoriaMixin
from auditoria.models import RegistroAuditoria
from catalogos.models import TipoAtencion, SubAtencion, SolicitudCatalogoGeneral
from evidencias.models import Evidencia
from usuarios.models import SolicitudTransferencia
from django.urls import reverse
from django.utils import timezone
from datetime import datetime


class AuditoriaFiltroFormTests(TestCase):
    def test_rango_de_fechas_invertido_no_es_valido(self):
        form = AuditoriaFiltroForm(
            data={'fecha_desde': '2026-10-18', 'fecha_hasta': '2026-10-17'}
        )

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_hasta', form.errors)

    def test_fecha_con_formato_invalido_no_es_valida(self):
        form = AuditoriaFiltroForm(data={'fecha_desde': 'ayer'})

        self.assertFalse(form.is_valid())
        self.assertIn('fecha_desde', form.errors)


class AuditoriaTerritorialTests(DatosAuditoriaMixin, TestCase):
    def listado(self, datos=None):
        return self.client.get(reverse('auditoria:lista'), datos or {})

    def test_administrador_global_sin_delegacion(self):
        usuario = self.usuarios['administrador']
        usuario.perfil.delegaciones.clear()
        usuario.perfil.delegacion = None
        usuario.perfil.save()
        self.entrar('administrador')
        respuesta = self.listado()
        self.assertContains(respuesta, self.evento_a.descripcion)
        self.assertContains(respuesta, self.evento_b.descripcion)

    def test_roles_territoriales_y_menu(self):
        for rol in ('delegado', 'coordinador'):
            with self.subTest(rol=rol):
                self.entrar(rol)
                respuesta = self.listado()
                self.assertContains(respuesta, self.evento_a.descripcion)
                self.assertNotContains(respuesta, self.evento_b.descripcion)
                self.assertContains(respuesta, 'href="/auditoria/"')
                self.assertNotIn(self.usuarios['verificador'],
                                 respuesta.context['form'].fields['usuario'].queryset)
                self.assertNotContains(respuesta, 'secreto_b')

    def test_roles_operativos_denegados(self):
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            self.assertEqual(self.listado().status_code, 403)

    def test_sin_alcance_o_delegacion_inactiva_no_hay_fallback_global(self):
        for rol in ('coordinador', 'delegado'):
            usuario = self.usuarios[rol]
            usuario.perfil.delegaciones.clear()
            self.entrar(rol)
            session = self.client.session
            session['delegacion_activa_id'] = self.b.pk
            session.save()
            self.assertFalse(self.listado().context['registros'])
        self.a.activa = False
        self.a.save()
        self.usuarios['coordinador'].perfil.delegaciones.add(self.a)
        self.entrar('coordinador')
        self.assertFalse(self.listado().context['registros'])

    def test_cambio_de_delegacion_autorizada(self):
        self.usuarios['coordinador'].perfil.delegaciones.add(self.b)
        self.entrar('coordinador')
        session = self.client.session
        session['delegacion_activa_id'] = self.b.pk
        session.save()
        respuesta = self.listado()
        self.assertContains(respuesta, self.evento_b.descripcion)
        self.assertNotContains(respuesta, self.evento_a.descripcion)

    def test_manipulacion_get_nunca_amplia_alcance(self):
        for rol in ('coordinador', 'delegado'):
            self.entrar(rol)
            for datos in (
                {'usuario': self.usuarios['verificador'].pk},
                {'accion': 'secreto_b'}, {'modulo': 'usuarios'},
                {'buscar': 'Información exclusiva B'},
                {'delegacion': self.b.pk, 'modulo': 'actividades', 'buscar': 'exclusiva'},
            ):
                with self.subTest(rol=rol, datos=datos):
                    self.assertFalse(self.listado(datos).context['registros'])

    def test_relaciones_reales_y_ambiguos_excluidos(self):
        compromiso_a = self.compromiso(self.a)
        compromiso_b = self.compromiso(self.b)
        evidencia_a = Evidencia.objects.create(atencion=self.actividad_a,
                                               subido_por=self.usuarios['funcionario'], archivo='a.jpg')
        evidencia_b = Evidencia.objects.create(compromiso=compromiso_b,
                                               subido_por=self.usuarios['funcionario'], archivo='b.jpg')
        tipo_a = TipoAtencion.objects.create(codigo='TA', nombre='Local',
                                            es_general=False, delegacion=self.a)
        sub_a = SubAtencion.objects.create(nombre='Sub local', tipo=tipo_a,
                                           es_general=False, delegacion=self.a)
        evidencia_agenda_a = Evidencia.objects.create(
            compromiso=compromiso_a, subido_por=self.usuarios['funcionario'], archivo='agenda.jpg')
        solicitud = SolicitudTransferencia.objects.create(
            usuario=self.usuarios['funcionario'], solicitante=self.usuarios['coordinador'],
            delegacion_origen=self.a, delegacion_destino=self.b)
        catalogo = SolicitudCatalogoGeneral.objects.create(
            tipo_solicitud='categoria', codigo='SG', nombre='Solicitud',
            solicitante=self.usuarios['delegado'], delegacion_solicitante=self.a)
        permitidos = [self.evento(objeto).pk for objeto in
                      (compromiso_a, evidencia_a, evidencia_agenda_a, tipo_a, sub_a,
                       solicitud, catalogo, self.sub)]
        # Subcategoría general: no es territorial.
        general = permitidos.pop()
        ocultos = [self.evento(objeto).pk for objeto in
                   (compromiso_b, evidencia_b, self.tipo, self.usuarios['funcionario'])]
        ocultos.append(general)
        huerfano = RegistroAuditoria.objects.create(modelo='atenciones.AtencionCiudadana',
                                                    objeto_id='inexistente', accion='crear')
        ocultos.append(huerfano.pk)
        ambiguo = RegistroAuditoria.objects.create(
            modelo='atenciones.AtencionCiudadana', objeto_id=f'{self.actividad_a.pk}texto', accion='crear')
        ocultos.append(ambiguo.pk)
        self.entrar('coordinador')
        ids = {r.pk for r in self.listado().context['registros']}
        self.assertTrue(set(permitidos).issubset(ids))
        self.assertTrue(set(ocultos).isdisjoint(ids))
        self.entrar('administrador')
        ids = {r.pk for r in self.listado().context['registros']}
        self.assertTrue(set(ocultos).issubset(ids))

    def test_filtros_y_dia_final_timezone(self):
        usuario = self.usuarios['coordinador']
        self.evento_a.usuario = usuario
        self.evento_a.save()
        fecha = timezone.make_aware(datetime(2026, 10, 26, 23, 59, 59))
        RegistroAuditoria.objects.filter(pk=self.evento_a.pk).update(timestamp=fecha)
        self.entrar('administrador')
        filtros = {'usuario': usuario.pk, 'accion': 'crear', 'modulo': 'actividades',
                   'buscar': 'territorial A', 'fecha_desde': '2026-10-26', 'fecha_hasta': '2026-10-26'}
        for clave, valor in filtros.items():
            self.assertIn(self.evento_a, self.listado({clave: valor}).context['registros'])
        self.assertEqual([r.pk for r in self.listado(filtros).context['registros']], [self.evento_a.pk])
        self.assertNotIn(self.evento_a, self.listado({'fecha_hasta': '2026-10-25'}).context['registros'])
        self.assertNotIn(self.evento_a, self.listado({'fecha_desde': '2026-10-27'}).context['registros'])

    def test_paginacion_conserva_filtros_sin_duplicar_page(self):
        for numero in range(51):
            self.evento(self.actividad_a, descripcion=f'Paginación {numero}')
        self.entrar('coordinador')
        respuesta = self.listado({'accion': 'crear', 'modulo': 'actividades',
                                 'buscar': 'Paginación', 'page': 2})
        self.assertEqual(len(respuesta.context['registros']), 1)
        self.assertNotIn('page=', respuesta.context['query_params'])
        self.assertContains(respuesta, 'accion=crear&amp;modulo=actividades')
