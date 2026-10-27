from django.conf import settings
from django.db import models
from django.utils import timezone

from catalogos.models import SubAtencion, TipoAtencion
from usuarios.models import Delegacion


class AtencionCiudadana(models.Model):
    class Estado(models.TextChoices):
        REGISTRADA = 'registrada', 'Registrada'
        EN_PROCESO = 'en_proceso', 'En proceso'
        CERRADA = 'cerrada', 'Cerrada'

    titulo = models.CharField('Título', max_length=200)
    fecha = models.DateField('Fecha de la actividad')
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.REGISTRADA,
    )
    activo = models.BooleanField('Habilitada', default=True)
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
    va_al_tubo = models.BooleanField('Va al tubo', default=False)
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
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='atenciones_creadas',
        verbose_name='Creado por',
    )
    fecha_registro = models.DateTimeField('Fecha de registro', auto_now_add=True)

    class Meta:
        verbose_name = 'Atención ciudadana'
        verbose_name_plural = 'Atenciones ciudadanas'
        ordering = ['-fecha_registro']

    def __str__(self):
        return f'{self.solicitante} — {self.tipo}'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(
                'delegacion_id',
            ).first()
            if original:
                self.delegacion_id = original['delegacion_id']
        return super().save(*args, **kwargs)

    @property
    def creador_historico_display(self):
        if self.creado_por is None:
            return 'Usuario histórico/no disponible'

        nombre = self.creado_por.get_full_name() or self.creado_por.username
        from usuarios.models import Perfil

        es_administrador = self.creado_por.is_superuser or Perfil.objects.filter(
            usuario=self.creado_por,
            activo=True,
            usuario__is_active=True,
            rol__codigo='administrador',
            rol__activo=True,
        ).exists()
        sigue_autorizado = Perfil.objects.filter(
            usuario=self.creado_por,
            delegaciones=self.delegacion,
        ).exists()
        if not es_administrador and not sigue_autorizado:
            return f'Ex funcionario {nombre}'
        return nombre

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


class HistorialEstadoActividad(models.Model):
    actividad = models.ForeignKey(AtencionCiudadana, on_delete=models.PROTECT,
                                   related_name='historial_estados', verbose_name='Actividad')
    estado_anterior = models.CharField('Estado anterior', max_length=20,
        choices=AtencionCiudadana.Estado.choices, blank=True, default='')
    estado_nuevo = models.CharField('Estado nuevo', max_length=20, choices=AtencionCiudadana.Estado.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='transiciones_actividad', verbose_name='Usuario')
    fecha_hora = models.DateTimeField('Fecha y hora', default=timezone.now, editable=False)
    motivo = models.TextField('Motivo', blank=True)

    class Meta:
        verbose_name = 'Historial de estado de Actividad'
        verbose_name_plural = 'Historial de estados de Actividades'
        ordering = ['-fecha_hora', '-pk']
        indexes = [models.Index(fields=['actividad', 'fecha_hora'], name='atenc_hist_estado_fecha_idx')]
        constraints = [
            models.CheckConstraint(condition=(models.Q(estado_anterior='')
                | models.Q(estado_anterior__in=AtencionCiudadana.Estado.values)),
                name='atenc_hist_anterior_valido'),
            models.CheckConstraint(condition=models.Q(estado_nuevo__in=AtencionCiudadana.Estado.values),
                name='atenc_hist_nuevo_valido'),
            models.CheckConstraint(condition=~models.Q(estado_anterior=models.F('estado_nuevo')),
                name='atenc_hist_transicion_real'),
        ]
