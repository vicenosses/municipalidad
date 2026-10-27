from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.db import transaction


class Periodo(models.Model):
    nombre = models.CharField('Nombre', max_length=150)
    fecha_inicio = models.DateField('Fecha inicio')
    fecha_fin = models.DateField('Fecha fin')
    activo = models.BooleanField('Activo', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='periodos_creados', verbose_name='Creado por',
    )
    creado_en = models.DateTimeField('Fecha creación', auto_now_add=True)
    actualizado_en = models.DateTimeField('Última actualización', auto_now=True)

    class Meta:
        verbose_name = 'Período'
        verbose_name_plural = 'Períodos'
        ordering = ['-fecha_inicio', '-pk']
        constraints = [models.CheckConstraint(
            condition=models.Q(fecha_inicio__lte=models.F('fecha_fin')),
            name='sgr_periodo_fechas_validas',
        )]

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('sgr:periodo_detalle', args=[self.pk])

    def clean(self):
        super().clean()
        self.nombre = ' '.join((self.nombre or '').split())
        errores = {}
        if not self.nombre:
            errores['nombre'] = 'El nombre no puede estar vacío.'
        fechas_validas = self.fecha_inicio and self.fecha_fin
        if fechas_validas and self.fecha_inicio > self.fecha_fin:
            errores['fecha_fin'] = 'La fecha fin debe ser igual o posterior a la fecha inicio.'
            fechas_validas = False
        if self.activo:
            otros = type(self).objects.filter(activo=True).exclude(pk=self.pk)
            # casefold evita depender de la collation del motor para los nombres.
            if self.nombre and any(
                ' '.join(nombre.split()).casefold() == self.nombre.casefold()
                for nombre in otros.values_list('nombre', flat=True)
            ):
                errores['nombre'] = 'Ya existe un período activo con este nombre.'
            if fechas_validas and otros.filter(
                fecha_inicio__lte=self.fecha_fin, fecha_fin__gte=self.fecha_inicio,
            ).exists():
                errores['fecha_inicio'] = 'Las fechas se superponen con otro período activo.'
        if self.pk:
            aportes = AporteIndicador.objects.filter(indicador__meta__periodo_id=self.pk)
            if not self.activo and aportes.exists():
                errores['__all__'] = 'No puede desactivar un período con Actividades vinculadas.'
            if fechas_validas and aportes.exclude(
                actividad__fecha__range=(self.fecha_inicio, self.fecha_fin)
            ).exists():
                errores['fecha_inicio'] = 'Las fechas dejarían Actividades vinculadas fuera del período.'
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.nombre = ' '.join((self.nombre or '').split())
        self.full_clean()
        return super().save(*args, **kwargs)


class Meta(models.Model):
    periodo = models.ForeignKey(Periodo, on_delete=models.PROTECT, related_name='metas',
                               verbose_name='Período')
    delegacion = models.ForeignKey('usuarios.Delegacion', on_delete=models.PROTECT,
                                  related_name='metas', verbose_name='Delegación')
    nombre = models.CharField('Nombre', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    activo = models.BooleanField('Activa', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='metas_creadas', verbose_name='Creado por',
    )
    creado_en = models.DateTimeField('Fecha creación', auto_now_add=True)
    actualizado_en = models.DateTimeField('Última actualización', auto_now=True)

    class Meta:
        verbose_name = 'Meta'
        verbose_name_plural = 'Metas'
        ordering = ['-periodo__fecha_inicio', 'nombre', 'pk']

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('sgr:meta_detalle', args=[self.pk])

    def clean(self):
        super().clean()
        self.nombre = ' '.join((self.nombre or '').split())
        errores = {}
        if not self.nombre:
            errores['nombre'] = 'El nombre no puede estar vacío.'
        original = type(self).objects.filter(pk=self.pk).values(
            'periodo_id', 'delegacion_id', 'nombre', 'descripcion', 'activo',
        ).first() if self.pk else None
        if original and (self.periodo_id != original['periodo_id']
                         or self.delegacion_id != original['delegacion_id']):
            errores['__all__'] = 'El período y la delegación no pueden cambiar después de crear la Meta.'
        periodo_activo = Periodo.objects.filter(pk=self.periodo_id).values_list('activo', flat=True).first()
        if periodo_activo is False and (
            original is None or any(getattr(self, campo) != valor for campo, valor in original.items())
        ):
            errores['__all__'] = 'No se pueden modificar Metas de un período inactivo. Reactive primero el período.'
        if self.activo and self.periodo_id and self.delegacion_id and self.nombre:
            nombres = type(self).objects.filter(
                periodo_id=self.periodo_id, delegacion_id=self.delegacion_id, activo=True,
            ).exclude(pk=self.pk).values_list('nombre', flat=True)
            if any(' '.join(nombre.split()).casefold() == self.nombre.casefold() for nombre in nombres):
                errores['nombre'] = 'Ya existe una Meta activa con este nombre en el período y delegación.'
        if self.pk and not self.activo and AporteIndicador.objects.filter(indicador__meta_id=self.pk).exists():
            errores['__all__'] = 'No puede desactivar una Meta con Actividades vinculadas.'
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.nombre = ' '.join((self.nombre or '').split())
        self.full_clean()
        return super().save(*args, **kwargs)


class Indicador(models.Model):
    class Unidad(models.TextChoices):
        PORCENTAJE = 'porcentaje', 'Porcentaje'
        CANTIDAD = 'cantidad', 'Cantidad'
        DIAS = 'dias', 'Días'
        HORAS = 'horas', 'Horas'
        OTRA = 'otra', 'Otra'

    class Sentido(models.TextChoices):
        MAYOR = 'mayor', 'Mayor es mejor'
        MENOR = 'menor', 'Menor es mejor'

    meta = models.ForeignKey(Meta, on_delete=models.PROTECT, related_name='indicadores',
                             verbose_name='Meta')
    nombre = models.CharField('Nombre', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    unidad_medida = models.CharField('Unidad de medida', max_length=20, choices=Unidad.choices)
    unidad_personalizada = models.CharField('Unidad personalizada', max_length=80, blank=True)
    sentido = models.CharField('Sentido', max_length=10, choices=Sentido.choices)
    valor_objetivo = models.DecimalField('Valor objetivo', max_digits=12, decimal_places=2,
                                        validators=[MinValueValidator(Decimal('0'))])
    ponderacion = models.DecimalField('Ponderación (%)', max_digits=5, decimal_places=2,
        null=True, blank=True, validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        help_text='Vacío: ponderación no configurada. Los Indicadores activos requieren un peso positivo.')
    activo = models.BooleanField('Activo', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='indicadores_creados', verbose_name='Creado por',
    )
    creado_en = models.DateTimeField('Fecha creación', auto_now_add=True)
    actualizado_en = models.DateTimeField('Última actualización', auto_now=True)

    class Meta:
        verbose_name = 'Indicador'
        verbose_name_plural = 'Indicadores'
        ordering = ['nombre', 'pk']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ponderacion__isnull=True) | models.Q(ponderacion__gte=0, ponderacion__lte=100),
                name='sgr_indicador_ponderacion_rango'),
            models.CheckConstraint(condition=models.Q(valor_objetivo__gte=0),
                                   name='sgr_indicador_objetivo_no_negativo'),
            models.CheckConstraint(condition=(~models.Q(unidad_medida='porcentaje')
                                              | models.Q(valor_objetivo__lte=100)),
                                   name='sgr_indicador_porcentaje_valido'),
        ]

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse('sgr:indicador_detalle', args=[self.pk])

    @property
    def unidad_display(self):
        return self.unidad_personalizada if self.unidad_medida == self.Unidad.OTRA else self.get_unidad_medida_display()

    @property
    def objetivo_display(self):
        valor = format(self.valor_objetivo, 'f')
        if '.' in valor:
            valor = valor.rstrip('0').rstrip('.')
        sufijo = {
            self.Unidad.PORCENTAJE: '%', self.Unidad.CANTIDAD: '',
            self.Unidad.DIAS: 'días', self.Unidad.HORAS: 'horas',
            self.Unidad.OTRA: self.unidad_personalizada,
        }.get(self.unidad_medida, '')
        return f'{valor} {sufijo}'.strip()

    @property
    def ponderacion_display(self):
        if self.ponderacion is None:
            return 'Ponderación no configurada'
        valor = format(self.ponderacion, 'f')
        if '.' in valor:
            valor = valor.rstrip('0').rstrip('.')
        return f'{valor}%'

    def normalizar(self):
        self.nombre = ' '.join((self.nombre or '').split())
        self.unidad_personalizada = (
            ' '.join((self.unidad_personalizada or '').split())
            if self.unidad_medida == self.Unidad.OTRA else ''
        )

    def clean(self):
        super().clean()
        self.normalizar()
        errores = {}
        if not self.nombre:
            errores['nombre'] = 'El nombre no puede estar vacío.'
        if self.unidad_medida == self.Unidad.OTRA and not self.unidad_personalizada:
            errores['unidad_personalizada'] = 'Indique la unidad personalizada.'
        valor = self.valor_objetivo
        if isinstance(valor, Decimal) and valor.is_finite():
            if valor < 0:
                errores['valor_objetivo'] = 'El valor objetivo no puede ser negativo.'
            elif self.activo and valor == 0:
                errores['valor_objetivo'] = 'Un Indicador activo requiere un valor objetivo mayor que cero.'
            elif self.unidad_medida == self.Unidad.PORCENTAJE and valor > 100:
                errores['valor_objetivo'] = 'El porcentaje objetivo no puede superar 100.'
        peso = self.ponderacion
        if isinstance(peso, Decimal) and peso.is_finite() and 0 <= peso <= 100:
            if self.activo and peso == 0:
                errores['ponderacion'] = 'La ponderación configurada de un Indicador activo debe ser positiva.'
            if self.activo and self.meta_id:
                asignado = type(self).objects.filter(meta_id=self.meta_id, activo=True).exclude(
                    pk=self.pk).aggregate(total=models.Sum('ponderacion'))['total'] or Decimal('0')
                if asignado + peso > 100:
                    errores['ponderacion'] = 'La suma de ponderaciones activas de la Meta no puede superar 100%.'
        campos = ('meta_id', 'nombre', 'descripcion', 'unidad_medida', 'unidad_personalizada',
                  'sentido', 'valor_objetivo', 'ponderacion', 'activo')
        original = type(self).objects.filter(pk=self.pk).values(*campos).first() if self.pk else None
        if original and self.meta_id != original['meta_id']:
            errores['__all__'] = 'La Meta de un Indicador no puede cambiar después de crearlo.'
        estructura = Meta.objects.filter(pk=self.meta_id).values('activo', 'periodo__activo').first()
        if estructura and not (estructura['activo'] and estructura['periodo__activo']) and (
            original is None or any(getattr(self, campo) != valor for campo, valor in original.items())
        ):
            errores['__all__'] = 'Reactive la Meta y su Período antes de modificar Indicadores.'
        if self.activo and self.meta_id and self.nombre:
            nombres = type(self).objects.filter(meta_id=self.meta_id, activo=True).exclude(
                pk=self.pk).values_list('nombre', flat=True)
            if any(' '.join(nombre.split()).casefold() == self.nombre.casefold() for nombre in nombres):
                errores['nombre'] = 'Ya existe un Indicador activo con este nombre en la Meta.'
        if self.pk and not self.activo and self.aportes.exists():
            errores['__all__'] = 'No puede desactivar un Indicador con Actividades vinculadas.'
        if original and original['valor_objetivo'] != self.valor_objetivo and self.tiene_vinculaciones:
            if not getattr(self, '_motivo_objetivo', '').strip():
                errores['__all__'] = 'Indique el motivo del cambio de objetivo: existen Actividades vinculadas.'
        if original and original['ponderacion'] != self.ponderacion and self.tiene_vinculaciones:
            if not getattr(self, '_motivo_ponderacion', '').strip():
                errores['ponderacion'] = 'Indique el motivo del cambio de ponderación: existen Actividades vinculadas.'
        if errores:
            raise ValidationError(errores)

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.normalizar()
        # Serializa cambios de todos los Indicadores de la misma Meta antes de sumar.
        if self.meta_id:
            Meta.objects.select_for_update().get(pk=self.meta_id)
        original = type(self).objects.select_for_update().filter(pk=self.pk).values(
            'valor_objetivo', 'ponderacion', 'activo').first() if self.pk else None
        anterior = original['valor_objetivo'] if original else None
        self.full_clean()
        cambio = anterior is not None and anterior != self.valor_objetivo and self.tiene_vinculaciones
        cambio_peso = original is not None and original['ponderacion'] != self.ponderacion
        campos_actualizados = kwargs.get('update_fields')
        if cambio and campos_actualizados is not None and 'valor_objetivo' not in campos_actualizados:
            raise ValidationError('El valor objetivo debe incluirse en los campos guardados para registrar su cambio.')
        if cambio and not getattr(self, '_actor_objetivo', None):
            raise ValidationError('El cambio de objetivo requiere identificar al usuario responsable.')
        if campos_actualizados is not None and original:
            for campo in ('ponderacion', 'activo'):
                if original[campo] != getattr(self, campo) and campo not in campos_actualizados:
                    raise ValidationError(f'El campo {campo} debe incluirse en los campos guardados.')
        if cambio_peso and not getattr(self, '_actor_ponderacion', None):
            raise ValidationError('El cambio de ponderación requiere identificar al usuario responsable.')
        with transaction.atomic():
            resultado = super().save(*args, **kwargs)
            if cambio:
                HistorialObjetivoIndicador.objects.create(
                    indicador=self, valor_anterior=anterior, valor_nuevo=self.valor_objetivo,
                    motivo=self._motivo_objetivo.strip(), usuario=self._actor_objetivo,
                )
                from auditoria.utils import registrar_auditoria
                registrar_auditoria(
                    getattr(self, '_request_objetivo', None), 'cambiar_objetivo_indicador', self,
                    f'Objetivo: {anterior} → {self.valor_objetivo}. Motivo: {self._motivo_objetivo.strip()}',
                )
            if cambio_peso:
                motivo = getattr(self, '_motivo_ponderacion', '').strip()
                HistorialPonderacionIndicador.objects.create(
                    indicador=self, valor_anterior=original['ponderacion'], valor_nuevo=self.ponderacion,
                    motivo=motivo, usuario=self._actor_ponderacion)
                from auditoria.utils import registrar_auditoria
                previo = original['ponderacion'] if original['ponderacion'] is not None else 'Sin configurar'
                nuevo = self.ponderacion if self.ponderacion is not None else 'Sin configurar'
                registrar_auditoria(getattr(self, '_request_ponderacion', None),
                    'cambiar_ponderacion_indicador', self,
                    f'Ponderación: {previo} → {nuevo}. Motivo: {motivo}')
            return resultado

    @property
    def tiene_vinculaciones(self):
        return self.aportes.exists() or EventoAporte.objects.filter(
            models.Q(indicador_anterior_id=self.pk) | models.Q(indicador_nuevo_id=self.pk)
        ).exists()


class AporteIndicador(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        REQUIERE_CORRECCION = 'requiere_correccion', 'Requiere corrección'
        CUMPLE = 'cumple', 'Cumple'
        NO_CUMPLE = 'no_cumple', 'No cumple'

    actividad = models.OneToOneField('atenciones.AtencionCiudadana', on_delete=models.PROTECT,
                                     related_name='aporte_indicador', verbose_name='Actividad')
    indicador = models.ForeignKey(Indicador, on_delete=models.PROTECT, related_name='aportes')
    estado = models.CharField(max_length=25, choices=Estado.choices, default=Estado.PENDIENTE)
    valor_declarado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                          validators=[MinValueValidator(Decimal('0'))])
    valor_validado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                         validators=[MinValueValidator(Decimal('0'))])
    comentario = models.TextField(blank=True)
    validado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='aportes_validados')
    validado_en = models.DateTimeField(null=True, blank=True)
    corregir_indicador = models.BooleanField(default=False)
    corregir_valor = models.BooleanField(default=False)
    espera_cierre = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-actualizado_en', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(estado__in=('pendiente', 'requiere_correccion', 'cumple', 'no_cumple')),
                                   name='sgr_aporte_estado_valido'),
            models.CheckConstraint(condition=models.Q(valor_declarado__isnull=True) | models.Q(valor_declarado__gte=0),
                                   name='sgr_aporte_declarado_no_negativo'),
            models.CheckConstraint(condition=models.Q(valor_validado__isnull=True) | models.Q(valor_validado__gte=0),
                                   name='sgr_aporte_validado_no_negativo'),
        ]

    def clean(self):
        super().clean()
        if self.actividad_id and self.indicador_id:
            actividad = self.actividad
            indicador = self.indicador
            periodo = indicador.meta.periodo
            if indicador.meta.delegacion_id != actividad.delegacion_id:
                raise ValidationError('La Actividad y el Indicador deben pertenecer a la misma Delegación.')
            if not periodo.fecha_inicio <= actividad.fecha <= periodo.fecha_fin:
                raise ValidationError('La fecha de la Actividad no pertenece al período del Indicador.')
            if not (indicador.activo and indicador.meta.activo and periodo.activo):
                raise ValidationError('El Indicador, la Meta y el Período deben estar activos.')
            if indicador.unidad_medida == Indicador.Unidad.OTRA and self.valor_declarado is None:
                raise ValidationError({'valor_declarado': 'Declare el aporte para esta unidad personalizada.'})
        if self.estado in (self.Estado.REQUIERE_CORRECCION, self.Estado.NO_CUMPLE) and not self.comentario.strip():
            raise ValidationError({'comentario': 'Debe justificar la decisión.'})
        if self.estado == self.Estado.CUMPLE and self.valor_validado != self.valor_declarado and not self.comentario.strip():
            raise ValidationError({'comentario': 'Justifique la modificación del valor declarado.'})
        if self.estado == self.Estado.REQUIERE_CORRECCION and not (self.corregir_indicador or self.corregir_valor):
            raise ValidationError('Indique qué debe corregir el Funcionario.')


class EventoAporte(models.Model):
    aporte = models.ForeignKey(AporteIndicador, on_delete=models.PROTECT, related_name='historial')
    accion = models.CharField(max_length=50)
    indicador_anterior = models.ForeignKey(Indicador, on_delete=models.PROTECT, null=True, blank=True,
                                           related_name='+')
    indicador_nuevo = models.ForeignKey(Indicador, on_delete=models.PROTECT, related_name='+')
    estado_anterior = models.CharField(max_length=25, blank=True)
    estado_nuevo = models.CharField(max_length=25, choices=AporteIndicador.Estado.choices)
    declarado_anterior = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    declarado_nuevo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    validado_anterior = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    validado_nuevo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    comentario = models.TextField(blank=True)
    corregir_indicador = models.BooleanField(default=False)
    corregir_valor = models.BooleanField(default=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField()

    class Meta:
        ordering = ['-creado_en', '-pk']

    @property
    def accion_display(self):
        from auditoria.presentacion import etiqueta_accion
        return etiqueta_accion(self.accion)

    @property
    def estado_anterior_display(self):
        return dict(AporteIndicador.Estado.choices).get(self.estado_anterior, 'Sin propuesta anterior')


class HistorialObjetivoIndicador(models.Model):
    indicador = models.ForeignKey(Indicador, on_delete=models.PROTECT, related_name='historial_objetivo')
    valor_anterior = models.DecimalField(max_digits=12, decimal_places=2)
    valor_nuevo = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']


class HistorialPonderacionIndicador(models.Model):
    indicador = models.ForeignKey(Indicador, on_delete=models.PROTECT, related_name='historial_ponderacion')
    valor_anterior = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    valor_nuevo = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    motivo = models.TextField(blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']
