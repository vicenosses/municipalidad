from django.conf import settings
from django.db import models


class RegistroAuditoria(models.Model):
    """Historial de operaciones realizadas en el SGR."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_auditoria',
        verbose_name='Usuario',
    )
    accion = models.CharField('Acción', max_length=50)
    modelo = models.CharField('Modelo', max_length=80)
    objeto_id = models.CharField('ID del objeto', max_length=64, blank=True)
    descripcion = models.TextField('Descripción')
    ip = models.GenericIPAddressField('Dirección IP', null=True, blank=True)
    timestamp = models.DateTimeField('Fecha y hora', auto_now_add=True)

    class Meta:
        verbose_name = 'Registro de auditoría'
        verbose_name_plural = 'Registros de auditoría'
        ordering = ['-timestamp']

    def __str__(self):
        usuario = self.usuario.username if self.usuario else 'sistema'
        return f'{self.timestamp:%Y-%m-%d %H:%M} — {usuario} — {self.accion}'
