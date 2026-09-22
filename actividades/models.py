from django.conf import settings
from django.db import models

from usuarios.models import Delegacion


class Actividad(models.Model):
    """Registro operativo diario de un funcionario."""

    class Estado(models.TextChoices):
        REGISTRADA = 'registrada', 'Registrada'
        EN_PROCESO = 'en_proceso', 'En proceso'
        CERRADA = 'cerrada', 'Cerrada'

    titulo = models.CharField('Título', max_length=200)
    descripcion = models.TextField('Descripción')
    fecha = models.DateField('Fecha de la actividad')
    funcionario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='actividades',
        verbose_name='Funcionario',
    )
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='actividades',
        verbose_name='Delegación',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.REGISTRADA,
    )
    creado = models.DateTimeField('Creado', auto_now_add=True)

    class Meta:
        verbose_name = 'Actividad'
        verbose_name_plural = 'Actividades'
        ordering = ['-fecha', '-creado']

    def __str__(self):
        return self.titulo
