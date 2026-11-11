from django.db import models

# Create your models here.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from usuarios.codigos import guardar_con_codigo_automatico


class Hito(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        EN_PROCESO = 'en_proceso', 'En proceso'
        COMPLETADO = 'completado', 'Completado'
        CANCELADO = 'cancelado', 'Cancelado'

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
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='hitos_asignados',
    )
    fecha_programada = models.DateField('Fecha programada')
    fecha_completada = models.DateField('Fecha completada', null=True, blank=True)
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
        padres = (self.actividad_id, self.gestion_social_id, self.compromiso_id)
        if sum(valor is not None for valor in padres) != 1:
            raise ValidationError('Un hito debe vincularse a una sola actividad, gestión o compromiso.')
        if self.estado == self.Estado.COMPLETADO and not self.fecha_completada:
            raise ValidationError({'fecha_completada': 'Indique la fecha de término del hito.'})
        if self.estado != self.Estado.COMPLETADO and self.fecha_completada:
            raise ValidationError({'fecha_completada': 'Solo los hitos completados pueden tener fecha de término.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(Hito, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'HIT', guardar)
        return super().save(*args, **kwargs)
