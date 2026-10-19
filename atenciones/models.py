from django.conf import settings
from django.db import models

from catalogos.models import SubAtencion, TipoAtencion
from usuarios.models import Delegacion


class AtencionCiudadana(models.Model):
    solicitante = models.CharField('Solicitante', max_length=180)
    tipo = models.ForeignKey(
        TipoAtencion,
        on_delete=models.PROTECT,
        related_name='atenciones',
        verbose_name='Tipo de atención',
    )
    subatencion = models.ForeignKey(
        SubAtencion,
        on_delete=models.PROTECT,
        related_name='atenciones',
        verbose_name='Subatención',
    )
    descripcion = models.TextField('Descripción')
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='atenciones',
        verbose_name='Delegación',
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='atenciones_responsable',
        verbose_name='Usuario responsable',
    )
    fecha_registro = models.DateTimeField('Fecha de registro', auto_now_add=True)

    class Meta:
        verbose_name = 'Atención ciudadana'
        verbose_name_plural = 'Atenciones ciudadanas'
        ordering = ['-fecha_registro']

    def __str__(self):
        return f'{self.solicitante} — {self.tipo}'

    @property
    def estado_evidencias(self):
        estados = {e.estado for e in self.evidencias.all()}
        if not estados:
            return 'sin_evidencia'
        if 'rechazada' in estados:
            return 'rechazada'
        if 'pendiente' in estados:
            return 'pendiente'
        return 'aprobada'

    @property
    def etiqueta_estado_evidencias(self):
        return {
            'pendiente': 'Pendiente',
            'aprobada': 'Aprobada',
            'rechazada': 'Rechazada',
            'sin_evidencia': 'Sin evidencia',
        }[self.estado_evidencias]

    @property
    def clase_estado_evidencias(self):
        return {
            'pendiente': 'bg-secondary text-white',
            'aprobada': 'bg-success text-white',
            'rechazada': 'bg-danger text-white',
            'sin_evidencia': 'bg-light text-secondary border',
        }[self.estado_evidencias]
