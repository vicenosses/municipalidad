from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from auditoria.models import RegistroAuditoria
from sgr.models import Indicador
from sgr.test_metas import DatosMetasMixin


class DatosIndicadoresMixin(DatosMetasMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.indicador_a = Indicador.objects.create(
            meta=cls.meta_a, nombre='Indicador territorial A', unidad_medida='porcentaje',
            sentido='mayor', valor_objetivo=90,
        )
        cls.indicador_b = Indicador.objects.create(
            meta=cls.meta_b, nombre='Indicador secreto B', descripcion='Información exclusiva B',
            unidad_medida='dias', sentido='menor', valor_objetivo=5,
        )

    def crear_indicador(self, **kwargs):
        datos = dict(meta=self.meta_a, nombre='Nuevo indicador', unidad_medida='cantidad',
                     sentido='mayor', valor_objetivo=Decimal('100'))
        datos.update(kwargs)
        return Indicador.objects.create(**datos)

    def url_indicador(self, accion, indicador=None):
        args = [(indicador or self.indicador_a).pk] if accion in ('detalle', 'editar', 'estado') else []
        return reverse(f'sgr:indicador_{accion}', args=args)

    def datos_indicador(self, **kwargs):
        datos = dict(meta=self.meta_a.pk, nombre='Nuevo indicador', descripcion='Detalle',
                     unidad_medida='cantidad', sentido='mayor', valor_objetivo='100.00')
        datos.update(kwargs)
        return datos


class IndicadorModeloTests(DatosIndicadoresMixin, TestCase):
    def test_valido_decimal_nombre_normalizado_y_fechas(self):
        indicador = self.crear_indicador(nombre='  Cantidad   completada ', valor_objetivo='12.50')
        self.assertEqual(indicador.nombre, 'Cantidad completada')
        self.assertEqual(indicador.valor_objetivo, Decimal('12.50'))
        self.assertTrue(indicador.activo)
        self.assertIsNotNone(indicador.creado_en)
        self.assertIsNotNone(indicador.actualizado_en)

    def test_nombre_vacio_o_blancos_rechazados(self):
        for nombre in ('', '  \t '):
            with self.subTest(nombre=nombre), self.assertRaises(ValidationError):
                self.crear_indicador(nombre=nombre)

    def test_objetivo_negativo_rechazado(self):
        with self.assertRaises(ValidationError):
            self.crear_indicador(valor_objetivo='-0.01')

    def test_porcentaje_mayor_100_rechazado(self):
        with self.assertRaises(ValidationError):
            self.crear_indicador(unidad_medida='porcentaje', valor_objetivo='100.01')

    def test_porcentaje_cero_inactivo_y_cien_activo_validos(self):
        for valor in (0, 100):
            indicador = self.crear_indicador(nombre=f'Porcentaje {valor}', unidad_medida='porcentaje',
                                             valor_objetivo=valor, activo=valor != 0)
            self.assertEqual(indicador.valor_objetivo, Decimal(valor))

    def test_cantidad_cero_inactiva_y_objetivo_mayor_cien_validos(self):
        for valor in (0, 1000):
            indicador = self.crear_indicador(nombre=f'Cantidad {valor}', valor_objetivo=valor, activo=valor != 0)
            self.assertEqual(indicador.valor_objetivo, Decimal(valor))

    def test_choices_y_precision_y_valores_no_finitos_rechazados(self):
        for datos in ({'unidad_medida': 'inexistente'}, {'sentido': 'otro'},
                      {'valor_objetivo': '1.001'}, {'valor_objetivo': '10000000000'},
                      {'valor_objetivo': 'NaN'}, {'valor_objetivo': 'Infinity'}):
            with self.subTest(datos=datos), self.assertRaises(ValidationError):
                self.crear_indicador(**datos)

    def test_duplicado_activo_misma_meta_rechazado(self):
        with self.assertRaises(ValidationError):
            self.crear_indicador(nombre='  INDICADOR TERRITORIAL A ')

    def test_mismo_nombre_otra_meta_permitido(self):
        indicador = self.crear_indicador(meta=self.meta_b, nombre=self.indicador_a.nombre)
        self.assertEqual(indicador.meta, self.meta_b)

    def test_inactivo_no_bloquea_y_reactivacion_duplicada_rechazada(self):
        antiguo = self.crear_indicador(activo=False)
        self.crear_indicador()
        antiguo.activo = True
        with self.assertRaises(ValidationError):
            antiguo.save()

    def test_meta_inactiva_bloquea_creacion_y_cambios_conserva_validacion_historica(self):
        self.meta_a.activo = False
        self.meta_a.save()
        self.indicador_a.full_clean()
        with self.assertRaises(ValidationError):
            self.crear_indicador()
        self.indicador_a.nombre = 'Cambio'
        with self.assertRaises(ValidationError):
            self.indicador_a.save()

    def test_periodo_inactivo_bloquea_creacion_y_cambio_estado(self):
        self.periodo.activo = False
        self.periodo.save()
        self.indicador_a.full_clean()
        with self.assertRaises(ValidationError):
            self.crear_indicador()
        self.indicador_a.activo = False
        with self.assertRaises(ValidationError):
            self.indicador_a.save()

    def test_unidad_otra_requiere_texto_estandar_lo_limpia(self):
        with self.assertRaises(ValidationError):
            self.crear_indicador(unidad_medida='otra', unidad_personalizada='   ')
        indicador = self.crear_indicador(unidad_medida='otra', unidad_personalizada='  kilómetros  ')
        self.assertEqual(indicador.unidad_personalizada, 'kilómetros')
        indicador.unidad_medida = 'horas'
        indicador.save()
        self.assertEqual(indicador.unidad_personalizada, '')

    def test_meta_inmutable_y_edicion_excluye_propio_objeto(self):
        self.indicador_a.descripcion = 'Actualizada'
        self.indicador_a.save()
        self.indicador_a.meta = self.meta_b
        with self.assertRaises(ValidationError):
            self.indicador_a.save()

    def test_creador_eliminado_conserva_indicador(self):
        usuario = get_user_model().objects.create_user(username='creador_indicador')
        indicador = self.crear_indicador(creado_por=usuario)
        usuario.delete()
        indicador.refresh_from_db()
        self.assertIsNone(indicador.creado_por)

    def test_presentacion_objetivo_sin_alterar_decimal(self):
        for unidad, valor, personalizada, esperado in (
            ('porcentaje', '90.00', '', '90 %'), ('cantidad', '100', '', '100'),
            ('dias', '5.00', '', '5 días'), ('horas', '24.00', '', '24 horas'),
            ('otra', '15.50', 'kilómetros', '15.5 kilómetros'),
        ):
            indicador = Indicador(unidad_medida=unidad, valor_objetivo=Decimal(valor),
                                   unidad_personalizada=personalizada)
            self.assertEqual(indicador.objetivo_display, esperado)
            self.assertEqual(indicador.valor_objetivo, Decimal(valor))


class IndicadorPermisosTests(DatosIndicadoresMixin, TestCase):
    def test_admin_global_y_crea_para_otra_delegacion(self):
        self.entrar('administrador')
        respuesta = self.client.get(self.url_indicador('lista'))
        self.assertContains(respuesta, self.indicador_a.nombre)
        self.assertContains(respuesta, self.indicador_b.nombre)
        self.assertEqual(self.client.get(self.url_indicador('detalle', self.indicador_b)).status_code, 200)
        respuesta = self.client.post(self.url_indicador('crear'), self.datos_indicador(meta=self.meta_b.pk))
        indicador = Indicador.objects.get(nombre='Nuevo indicador')
        self.assertRedirects(respuesta, indicador.get_absolute_url())
        self.assertEqual(indicador.meta, self.meta_b)
        self.assertEqual(indicador.creado_por, self.usuarios['administrador'])

    def test_delegado_coordinador_crean_y_editan_en_su_alcance(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            nombre = f'Creado {rol}'
            respuesta = self.client.post(self.url_indicador('crear'), self.datos_indicador(nombre=nombre))
            indicador = Indicador.objects.get(nombre=nombre)
            self.assertRedirects(respuesta, indicador.get_absolute_url())
            respuesta = self.client.post(self.url_indicador('editar', indicador),
                                         self.datos_indicador(nombre=f'Editado {rol}', valor_objetivo='12.50'))
            self.assertRedirects(respuesta, indicador.get_absolute_url())
            indicador.refresh_from_db()
            self.assertEqual(indicador.valor_objetivo, Decimal('12.50'))

    def test_post_meta_de_otro_territorio_rechazado_y_opciones_acotadas(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.url_indicador('crear'))
            self.assertNotIn(self.meta_b, respuesta.context['form'].fields['meta'].queryset)
            respuesta = self.client.post(self.url_indicador('crear'), self.datos_indicador(meta=self.meta_b.pk))
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn('meta', respuesta.context['form'].errors)
        self.assertEqual(Indicador.objects.count(), 2)
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_edicion_admin_solo_campos_propios_ignora_meta_actor_estado_manipulados(self):
        self.entrar('administrador')
        form = self.client.get(self.url_indicador('editar')).context['form']
        self.assertEqual(set(form.fields), {'nombre', 'descripcion', 'unidad_medida',
                                            'unidad_personalizada', 'sentido', 'valor_objetivo', 'ponderacion'})
        respuesta = self.client.post(self.url_indicador('editar'), self.datos_indicador(
            nombre='Editado', meta=self.meta_b.pk, unidad_medida='dias', sentido='menor',
            valor_objetivo='2.50', creado_por=self.usuarios['verificador'].pk, activo='false'))
        self.assertRedirects(respuesta, self.indicador_a.get_absolute_url())
        self.indicador_a.refresh_from_db()
        self.assertEqual(self.indicador_a.meta, self.meta_a)
        self.assertTrue(self.indicador_a.activo)
        self.assertIsNone(self.indicador_a.creado_por)
        self.assertEqual(self.indicador_a.sentido, 'menor')

    def test_admin_y_delegado_cambian_estado_coordinador_no(self):
        for rol, indicador in (('administrador', self.indicador_b), ('delegado', self.indicador_a)):
            self.entrar(rol)
            for valor in ('false', 'true'):
                self.assertRedirects(self.client.post(self.url_indicador('estado', indicador),
                                                       {'activo': valor}), indicador.get_absolute_url())
                indicador.refresh_from_db()
                self.assertEqual(indicador.activo, valor == 'true')
        self.entrar('coordinador')
        self.assertEqual(self.client.post(self.url_indicador('estado'), {'activo': 'false'}).status_code, 403)
        self.assertNotContains(self.client.get(self.url_indicador('detalle')), '/indicadores/1/cambiar-estado/')

    def test_otro_territorio_no_lista_ni_accede_por_url_directa(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            self.assertNotContains(self.client.get(self.url_indicador('lista')), self.indicador_b.nombre)
            for accion in ('detalle', 'editar'):
                self.assertEqual(self.client.get(self.url_indicador(accion, self.indicador_b)).status_code, 404)
            self.assertEqual(self.client.post(self.url_indicador('editar', self.indicador_b),
                                              self.datos_indicador()).status_code, 404)
            self.assertIn(self.client.post(self.url_indicador('estado', self.indicador_b),
                                           {'activo': 'false'}).status_code, (403, 404))

    def test_sin_delegacion_o_delegacion_inactiva_no_hay_fallback(self):
        for rol in ('delegado', 'coordinador'):
            self.usuarios[rol].perfil.delegaciones.clear()
            self.entrar(rol)
            session = self.client.session
            session['delegacion_activa_id'] = self.b.pk
            session.save()
            self.assertFalse(self.client.get(self.url_indicador('lista')).context['indicadores'])
            self.assertEqual(self.client.post(self.url_indicador('crear'), self.datos_indicador()).status_code, 403)
            self.assertEqual(self.client.post(self.url_indicador('editar'), self.datos_indicador()).status_code, 404)
            self.assertIn(self.client.post(self.url_indicador('estado'), {'activo': 'false'}).status_code, (403, 404))
        self.usuarios['delegado'].perfil.delegaciones.add(self.a)
        self.a.activa = False
        self.a.save()
        self.entrar('delegado')
        self.assertFalse(self.client.get(self.url_indicador('lista')).context['indicadores'])

    def test_funcionario_verificador_sin_acceso(self):
        for rol in ('funcionario', 'verificador'):
            self.entrar(rol)
            for accion in ('lista', 'crear', 'detalle', 'editar', 'estado'):
                self.assertEqual(self.client.get(self.url_indicador(accion)).status_code, 403)
                self.assertEqual(self.client.post(self.url_indicador(accion), self.datos_indicador()).status_code, 403)

    def test_estado_post_csrf_y_get_no_modifica(self):
        self.entrar('delegado')
        self.assertEqual(self.client.get(self.url_indicador('estado')).status_code, 405)
        self.indicador_a.refresh_from_db()
        self.assertTrue(self.indicador_a.activo)
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(self.usuarios['delegado'])
        self.assertEqual(cliente.post(self.url_indicador('estado'), {'activo': 'false'}).status_code, 403)
        respuesta = cliente.get(self.url_indicador('detalle'))
        self.assertContains(respuesta, 'csrfmiddlewaretoken')
        token = cliente.cookies['csrftoken'].value
        self.assertEqual(cliente.post(self.url_indicador('estado'), {'activo': 'false',
                                      'csrfmiddlewaretoken': token}).status_code, 302)

    def test_bloqueo_por_meta_y_periodo_inactivos_todos_roles(self):
        for padre in (self.meta_a, self.periodo):
            padre.activo = False
            padre.save()
            for rol in ('administrador', 'delegado', 'coordinador'):
                self.entrar(rol)
                respuesta = self.client.get(self.url_indicador('detalle'))
                self.assertContains(respuesta, self.indicador_a.nombre)
                self.assertNotContains(respuesta, f'/indicadores/{self.indicador_a.pk}/editar/')
                self.assertEqual(self.client.get(self.url_indicador('editar')).status_code, 403)
                self.assertEqual(self.client.post(self.url_indicador('editar'), self.datos_indicador()).status_code, 403)
                self.assertEqual(self.client.post(self.url_indicador('estado'), {'activo': 'false'}).status_code, 403)
                respuesta = self.client.post(self.url_indicador('crear'), self.datos_indicador())
                self.assertEqual(respuesta.status_code, 200)
                self.assertIn('meta', respuesta.context['form'].errors)
                respuesta = self.client.get(self.meta_a.get_absolute_url())
                self.assertContains(respuesta, self.indicador_a.nombre)
                self.assertNotContains(respuesta, 'Nuevo Indicador')
            padre.activo = True
            padre.save()
        self.assertEqual(Indicador.objects.count(), 2)
        self.assertFalse(RegistroAuditoria.objects.exists())

    def test_formulario_rechaza_numeros_y_choices_invalidos(self):
        self.entrar('administrador')
        for datos in ({'valor_objetivo': '-1'}, {'unidad_medida': 'porcentaje', 'valor_objetivo': '101'},
                      {'sentido': 'otro'}, {'valor_objetivo': 'NaN'},
                      {'unidad_medida': 'otra', 'unidad_personalizada': '  '}):
            respuesta = self.client.post(self.url_indicador('crear'), self.datos_indicador(**datos))
            self.assertEqual(respuesta.status_code, 200)
            self.assertTrue(respuesta.context['form'].errors)
        self.assertEqual(Indicador.objects.count(), 2)

    def test_reactivacion_duplicada_no_audita_y_post_repetido_no_duplica_evento(self):
        antiguo = self.crear_indicador(activo=False)
        self.crear_indicador()
        self.entrar('delegado')
        self.client.post(self.url_indicador('estado', antiguo), {'activo': 'true'})
        antiguo.refresh_from_db()
        self.assertFalse(antiguo.activo)
        for valor in ('true', 'incorrecto'):
            self.client.post(self.url_indicador('estado'), {'activo': valor})
        self.assertFalse(RegistroAuditoria.objects.exists())


class IndicadorIntegracionTests(DatosIndicadoresMixin, TestCase):
    def test_filtros_admin_y_combinaciones(self):
        meta = self.crear_meta(periodo=self.otro_periodo)
        otro = self.crear_indicador(meta=meta, activo=False, descripcion='Texto buscable',
                                    unidad_medida='horas', valor_objetivo=24)
        self.entrar('administrador')
        for filtros, ids in (
            ({'periodo': self.otro_periodo.pk}, {otro.pk}), ({'meta': self.meta_b.pk}, {self.indicador_b.pk}),
            ({'estado': 'inactivo'}, {otro.pk}), ({'unidad': 'dias'}, {self.indicador_b.pk}),
            ({'delegacion': self.b.pk}, {self.indicador_b.pk}), ({'buscar': 'buscable'}, {otro.pk}),
            ({'buscar': 'secreto'}, {self.indicador_b.pk}),
            ({'estado': 'activo', 'unidad': 'porcentaje', 'periodo': self.periodo.pk}, {self.indicador_a.pk}),
        ):
            with self.subTest(filtros=filtros):
                respuesta = self.client.get(self.url_indicador('lista'), filtros)
                self.assertEqual({i.pk for i in respuesta.context['indicadores']}, ids)

    def test_filtros_y_opciones_meta_no_filtran_otro_territorio(self):
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.url_indicador('lista'), {'delegacion': self.b.pk})
            self.assertEqual(list(respuesta.context['indicadores']), [self.indicador_a])
            self.assertNotIn(self.meta_b, respuesta.context['form'].fields['meta'].queryset)
            self.assertNotIn('delegacion', respuesta.context['form'].fields)
            for filtros in ({'meta': self.meta_b.pk}, {'buscar': 'exclusiva B'},
                            {'delegacion': self.b.pk, 'unidad': 'dias'}):
                self.assertFalse(self.client.get(self.url_indicador('lista'), filtros).context['indicadores'])

    def test_meta_detalle_solo_indicadores_correspondientes_y_permisos(self):
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(self.meta_a.get_absolute_url())
            self.assertContains(respuesta, self.indicador_a.nombre)
            self.assertNotContains(respuesta, self.indicador_b.nombre)
            self.assertContains(respuesta, 'Nuevo Indicador')
            self.assertEqual(self.client.get(self.meta_b.get_absolute_url()).status_code,
                             200 if rol == 'administrador' else 404)

    def test_creacion_desde_meta_bloquea_sustitucion_post(self):
        url = reverse('sgr:indicador_desde_meta', args=[self.meta_a.pk])
        for rol in ('administrador', 'delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(url)
            self.assertTrue(respuesta.context['form'].fields['meta'].disabled)
            nombre = f'Desde Meta {rol}'
            respuesta = self.client.post(url, self.datos_indicador(meta=self.meta_b.pk, nombre=nombre))
            indicador = Indicador.objects.get(nombre=nombre)
            self.assertRedirects(respuesta, indicador.get_absolute_url())
            self.assertEqual(indicador.meta, self.meta_a)

    def test_origen_otro_territorio_inactivo_y_sin_acceso_rechazados(self):
        self.entrar('delegado')
        url = reverse('sgr:indicador_desde_meta', args=[self.meta_b.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.datos_indicador()).status_code, 404)
        self.meta_a.activo = False
        self.meta_a.save()
        url = reverse('sgr:indicador_desde_meta', args=[self.meta_a.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.datos_indicador()).status_code, 403)
        self.entrar('funcionario')
        self.assertEqual(self.client.post(url, self.datos_indicador()).status_code, 403)

    def test_auditoria_cuatro_eventos_territoriales_y_periodo_global(self):
        self.entrar('administrador')
        self.client.post(self.url_indicador('crear'), self.datos_indicador())
        nuevo = Indicador.objects.get(nombre='Nuevo indicador')
        self.client.post(self.url_indicador('editar', nuevo), self.datos_indicador(nombre='Indicador editado'))
        for activo in ('false', 'true'):
            self.client.post(self.url_indicador('estado', nuevo), {'activo': activo})
        self.client.post(self.url_indicador('crear'), self.datos_indicador(nombre='Creado B', meta=self.meta_b.pk))
        self.client.post(reverse('sgr:periodo_editar', args=[self.periodo.pk]), {
            'nombre': self.periodo.nombre, 'fecha_inicio': '2026-01-01', 'fecha_fin': '2026-12-31'})
        RegistroAuditoria.objects.create(modelo='sgr.Meta', objeto_id=str(self.meta_a.pk),
                                         accion='crear_meta', descripcion='Meta territorial')
        self.assertEqual(set(RegistroAuditoria.objects.filter(modelo='sgr.Indicador').values_list(
            'accion', flat=True)), {'crear_indicador', 'editar_indicador', 'activar_indicador', 'desactivar_indicador'})
        url = reverse('auditoria:lista')
        respuesta = self.client.get(url, {'modulo': 'sgr'})
        self.assertEqual(len(respuesta.context['registros']), 7)
        self.assertIn(('sgr', 'SGR'), respuesta.context['form'].fields['modulo'].choices)
        self.assertContains(respuesta, 'Creado B')
        for rol in ('delegado', 'coordinador'):
            self.entrar(rol)
            respuesta = self.client.get(url, {'modulo': 'sgr'})
            self.assertEqual(len(respuesta.context['registros']), 5)
            self.assertNotContains(respuesta, 'Creado B')
            self.assertTrue(all(r.modelo != 'sgr.Periodo' for r in respuesta.context['registros']))

    def test_paginacion_conserva_filtros(self):
        for numero in range(51):
            self.crear_indicador(nombre=f'Paginado {numero:02d}')
        self.entrar('coordinador')
        respuesta = self.client.get(self.url_indicador('lista'), {'meta': self.meta_a.pk,
                                    'unidad': 'cantidad', 'buscar': 'Paginado', 'page': 2})
        self.assertEqual(len(respuesta.context['indicadores']), 1)
        self.assertNotIn('page=', respuesta.context['query_params'])
        self.assertContains(respuesta, 'unidad=cantidad&amp;buscar=Paginado')

    def test_nombre_visible_navegacion_y_objetivo_amigable(self):
        self.entrar('administrador')
        for url in (self.url_indicador('lista'), self.meta_a.get_absolute_url(), self.periodo.get_absolute_url()):
            respuesta = self.client.get(url)
            self.assertContains(respuesta, 'href="/sgr/periodos/">Prioridades y Metas</a>')
            self.assertContains(respuesta, 'Prioridades y Metas', count=1)
            self.assertContains(respuesta, '<span class="text-white">SGR</span>')
            self.assertContains(respuesta, 'Sistema de Gestión de Resultados')
        respuesta = self.client.get(self.url_indicador('detalle'))
        self.assertContains(respuesta, '90 %')
        self.assertContains(respuesta, 'Mayor es mejor')
        self.assertContains(respuesta, 'href="/sgr/indicadores/"')
