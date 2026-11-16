from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Territorio


class Hito(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        EN_PROCESO = 'en_proceso', 'En proceso'
        COMPLETADO = 'completado', 'Completado'
        CANCELADO = 'cancelado', 'Cancelado'

    class Periodicidad(models.TextChoices):
        UNICA = 'unica', 'Única'
        SEMANAL = 'semanal', 'Semanal'
        MENSUAL = 'mensual', 'Mensual'
        TRIMESTRAL = 'trimestral', 'Trimestral'
        ANUAL = 'anual', 'Anual'

    codigo = models.CharField('Código', max_length=30, unique=True, editable=False, blank=True)
    titulo = models.CharField('Título', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    actividad = models.ForeignKey(
        'atenciones.AtencionCiudadana', on_delete=models.PROTECT,
        null=True, blank=True, related_name='hitos',
    )
    gestion_social = models.ForeignKey(
        'gestion_social.GestionSocial', on_delete=models.PROTECT,
        null=True, blank=True, related_name='hitos',
    )
    compromiso = models.ForeignKey(
        'agenda.Compromiso', on_delete=models.PROTECT,
        null=True, blank=True, related_name='hitos',
    )
    actividades = models.ManyToManyField(
        'atenciones.AtencionCiudadana', blank=True, related_name='hitos_relacionados',
        verbose_name='Actividades relacionadas',
    )
    territorio = models.ForeignKey(
        Territorio, on_delete=models.PROTECT, null=True, blank=True, related_name='hitos',
    )
    asignacion_meta = models.ForeignKey(
        'sgr.AsignacionMeta', on_delete=models.PROTECT, null=True, blank=True,
        related_name='hitos',
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hitos_asignados',
    )
    fecha_programada = models.DateField('Fecha programada')
    fecha_completada = models.DateField('Fecha completada', null=True, blank=True)
    periodicidad = models.CharField(
        'Periodicidad', max_length=12, choices=Periodicidad.choices, default=Periodicidad.UNICA,
    )
    repetir_hasta = models.DateField('Repetir hasta', null=True, blank=True)
    repeticion_padre = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='ocurrencias',
    )
    estado = models.CharField('Estado', max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    motivo_cambio = models.TextField('Motivo de cambio', blank=True)
    activo = models.BooleanField('Activo', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='hitos_creados',
    )
    creado_en = models.DateTimeField('Creado', auto_now_add=True)
    actualizado_en = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        ordering = ['fecha_programada', 'pk']
        verbose_name = 'Hito'
        verbose_name_plural = 'Hitos'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(actividad__isnull=False, gestion_social__isnull=True, compromiso__isnull=True)
                    | models.Q(actividad__isnull=True, gestion_social__isnull=False, compromiso__isnull=True)
                    | models.Q(actividad__isnull=True, gestion_social__isnull=True, compromiso__isnull=False)
                ),
                name='hito_un_solo_registro_padre',
            ),
        ]
        indexes = [
            models.Index(fields=['responsable', 'estado', 'activo']),
            models.Index(fields=['fecha_programada', 'estado']),
        ]
        constraints += [
            models.UniqueConstraint(
                fields=['repeticion_padre', 'fecha_programada'],
                condition=models.Q(repeticion_padre__isnull=False),
                name='hito_una_ocurrencia_por_fecha',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.titulo}'

    @property
    def delegacion_id(self):
        if self.actividad_id:
            return self.actividad.delegacion_id
        if self.gestion_social_id:
            return self.gestion_social.delegacion_id
        if self.compromiso_id:
            return self.compromiso.delegacion_id
        return None

    def clean(self):
        super().clean()
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_programada,
            'No se puede crear ni modificar un hito de un período cerrado.',
        )
        padres = (self.actividad_id, self.gestion_social_id, self.compromiso_id)
        if sum(valor is not None for valor in padres) != 1:
            raise ValidationError('Un hito debe vincularse a una sola actividad, gestión o compromiso.')
        if self.estado == self.Estado.COMPLETADO and not self.fecha_completada:
            raise ValidationError({'fecha_completada': 'Indique la fecha de término del hito.'})
        if self.estado != self.Estado.COMPLETADO and self.fecha_completada:
            raise ValidationError({'fecha_completada': 'Solo los hitos completados pueden tener fecha de término.'})
        if self.repetir_hasta and self.repetir_hasta < self.fecha_programada:
            raise ValidationError({'repetir_hasta': 'La fecha final debe ser posterior al hito programado.'})
        if self.periodicidad == self.Periodicidad.UNICA and self.repetir_hasta:
            raise ValidationError({'repetir_hasta': 'Indique una periodicidad para repetir el hito.'})
        if self.periodicidad != self.Periodicidad.UNICA and not self.repetir_hasta:
            raise ValidationError({'repetir_hasta': 'Indique hasta cuándo se repetirá el hito.'})
        if self.asignacion_meta_id and (
            self.asignacion_meta.funcionario_id != self.responsable_id
            or self.asignacion_meta.meta.delegacion_id != self.delegacion_id
        ):
            raise ValidationError({'asignacion_meta': 'La meta debe estar asignada al responsable en esta delegación.'})
        if self.territorio_id and self.delegacion_id != self.territorio.delegacion_id:
            raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación del hito.'})
        fecha_padre = None
        if self.actividad_id:
            fecha_padre = self.actividad.fecha
        elif self.gestion_social_id:
            fecha_padre = self.gestion_social.fecha_ingreso
        elif self.compromiso_id:
            fecha_padre = self.compromiso.fecha_hora
        validar_periodo_abierto(
            fecha_padre,
            'No se puede asociar ni modificar un hito vinculado a un período cerrado.',
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(Hito, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'HIT', guardar)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_programada,
            'No se puede eliminar un hito de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


class HistorialHito(models.Model):
    hito = models.ForeignKey(Hito, on_delete=models.PROTECT, related_name='historial')
    accion = models.CharField('Acción', max_length=40)
    estado_anterior = models.CharField(max_length=20, blank=True)
    estado_nuevo = models.CharField(max_length=20, blank=True)
    motivo = models.TextField('Observación', blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='historial_hitos',
    )
    creado_en = models.DateTimeField('Fecha de seguimiento', auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']
        verbose_name = 'Seguimiento de hito'
        verbose_name_plural = 'Historial de hitos'

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.hito.fecha_programada,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.hito.fecha_programada,
            'No se puede eliminar seguimiento de un período cerrado.',
        )
        return super().delete(*args, **kwargs)
