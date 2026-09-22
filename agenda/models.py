from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from usuarios.models import Delegacion


class Compromiso(models.Model):
    """Evento o compromiso de la agenda compartida de la delegación."""

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        CUMPLIDO = 'cumplido', 'Cumplido'

    titulo = models.CharField('Título', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    fecha_hora = models.DateTimeField('Fecha y hora')
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='compromisos',
        verbose_name='Responsable',
    )
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='compromisos',
        verbose_name='Delegación',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    creado = models.DateTimeField('Creado', auto_now_add=True)

    class Meta:
        verbose_name = 'Compromiso'
        verbose_name_plural = 'Compromisos'
        ordering = ['fecha_hora']

    def __str__(self):
        return self.titulo

    @property
    def esta_vencido(self):
        return self.estado == self.Estado.PENDIENTE and self.fecha_hora < timezone.now()

    @property
    def proximo_a_vencer(self):
        ahora = timezone.now()
        limite = ahora + timedelta(days=7)
        return (
            self.estado == self.Estado.PENDIENTE
            and ahora <= self.fecha_hora <= limite
        )
