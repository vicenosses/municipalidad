import uuid

from django.conf import settings
from django.db import models

from actividades.models import Actividad


class Evidencia(models.Model):
    """Respaldo fotográfico asociado a una actividad operativa."""

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    actividad = models.ForeignKey(
        Actividad,
        on_delete=models.CASCADE,
        related_name='evidencias',
        verbose_name='Actividad',
    )
    archivo = models.ImageField('Archivo', upload_to='evidencias/%Y/%m/')
    codigo_respaldo = models.UUIDField(
        'Código de respaldo',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='evidencias_subidas',
        verbose_name='Subido por',
    )
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evidencias_validadas',
        verbose_name='Validado por',
    )
    comentario_validacion = models.TextField('Comentario de validación', blank=True)
    fecha_subida = models.DateTimeField('Fecha de subida', auto_now_add=True)
    fecha_validacion = models.DateTimeField('Fecha de validación', null=True, blank=True)

    class Meta:
        verbose_name = 'Evidencia'
        verbose_name_plural = 'Evidencias'
        ordering = ['-fecha_subida']

    def __str__(self):
        return str(self.codigo_respaldo)
