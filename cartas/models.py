from django.db import models

# Create your models here.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Delegacion, Territorio, Vecino


class Carta(models.Model):
    class Estado(models.TextChoices):
        INGRESADA = 'ingresada', 'Ingresada'
        ASIGNADA = 'asignada', 'Asignada'
        EN_PROCESO = 'en_proceso', 'En proceso'
        RESPONDIDA = 'respondida', 'Respondida'
        CERRADA = 'cerrada', 'Cerrada'

    codigo = models.CharField('Código', max_length=30, unique=True, editable=False, blank=True)
    asunto = models.CharField('Asunto', max_length=200)
    contenido = models.TextField('Contenido de la carta')
    respuesta = models.TextField('Respuesta', blank=True)
    vecino = models.ForeignKey(
        Vecino, on_delete=models.PROTECT, null=True, blank=True, related_name='cartas',
    )
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='cartas')
    territorio = models.ForeignKey(
        Territorio, on_delete=models.PROTECT, null=True, blank=True, related_name='cartas',
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cartas_asignadas',
    )
    estado = models.CharField('Estado', max_length=20, choices=Estado.choices, default=Estado.INGRESADA)
    fecha_ingreso = models.DateField('Fecha de ingreso', default=timezone.localdate)
    fecha_compromiso = models.DateField('Fecha de compromiso', null=True, blank=True)
    fecha_respuesta = models.DateField('Fecha de respuesta', null=True, blank=True)
    ingresa_al_tubo = models.BooleanField('Incluir en el tubo', default=True)
    activo = models.BooleanField('Activa', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cartas_creadas',
    )
    creado_en = models.DateTimeField('Creado', auto_now_add=True)
    actualizado_en = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        ordering = ['-fecha_ingreso', '-pk']
        verbose_name = 'Carta'
        verbose_name_plural = 'Cartas'
        indexes = [models.Index(fields=['delegacion', 'estado', 'activo'])]

    def __str__(self):
        return f'{self.codigo} — {self.asunto}'

    def clean(self):
        super().clean()
        if self.territorio_id and self.delegacion_id != self.territorio.delegacion_id:
            raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación.'})
        if self.vecino_id and self.territorio_id and self.vecino.territorio_id != self.territorio_id:
            raise ValidationError({'vecino': 'El vecino debe pertenecer al territorio seleccionado.'})
        if self.fecha_compromiso and self.fecha_ingreso and self.fecha_compromiso < self.fecha_ingreso:
            raise ValidationError({'fecha_compromiso': 'La fecha de compromiso no puede ser anterior al ingreso.'})
        if self.estado == self.Estado.RESPONDIDA and not self.respuesta.strip():
            raise ValidationError({'respuesta': 'Debe registrar una respuesta antes de marcar la carta como respondida.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(Carta, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'CAR', guardar)
        return super().save(*args, **kwargs)
