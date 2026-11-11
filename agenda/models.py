from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from sgr.periodos import validar_periodo_abierto
from usuarios.models import Delegacion


class Compromiso(models.Model):
    """Compromiso municipal con seguimiento, responsable y actividades asociadas."""

    class Estado(models.TextChoices):
        INGRESADO = 'ingresado', 'Ingresado'
        PENDIENTE = 'pendiente', 'Pendiente'
        EN_PROCESO = 'en_proceso', 'En proceso'
        REALIZADO = 'realizado', 'Realizado'
        CERRADO = 'cerrado', 'Cerrado'
        NO_APLICA = 'no_aplica', 'No aplica'

    titulo = models.CharField('Título', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    solicitante = models.CharField('Solicitante', max_length=180, blank=True)
    rut_solicitante = models.CharField('RUT del solicitante', max_length=20, blank=True)
    telefono_solicitante = models.CharField('Teléfono del solicitante', max_length=30, blank=True)
    area_apoyo = models.CharField('Área de apoyo', max_length=120, blank=True)
    observaciones = models.TextField('Observaciones', blank=True)
    fecha_hora = models.DateTimeField('Fecha y hora')
    fecha_realizacion = models.DateTimeField('Fecha de realización', null=True, blank=True)
    fecha_cierre = models.DateTimeField('Fecha de cierre', null=True, blank=True)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='compromisos',
        verbose_name='Responsable',
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='compromisos_creados',
        verbose_name='Creado por',
    )
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='compromisos',
        verbose_name='Delegación',
    )
    actividades = models.ManyToManyField(
        'atenciones.AtencionCiudadana',
        blank=True,
        related_name='compromisos',
        verbose_name='Actividades relacionadas',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.INGRESADO,
    )
    creado = models.DateTimeField('Creado', auto_now_add=True)

    class Meta:
        verbose_name = 'Compromiso'
        verbose_name_plural = 'Compromisos'
        ordering = ['fecha_hora']

    def clean(self):
        super().clean()
        validar_periodo_abierto(
            self.fecha_hora,
            'No se puede crear ni modificar un compromiso de un período cerrado.',
        )
        if self.pk:
            for fecha in self.actividades.values_list('fecha', flat=True):
                validar_periodo_abierto(
                    fecha,
                    'No se puede asociar ni modificar un compromiso vinculado a un período cerrado.',
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        validar_periodo_abierto(
            self.fecha_hora,
            'No se puede eliminar un compromiso de un período cerrado.',
        )
        return super().delete(*args, **kwargs)

    def __str__(self):
        return self.titulo

    @property
    def codigo(self):
        return f'TUB-{self.pk:06d}' if self.pk else ''

    @property
    def esta_vencido(self):
        return not self.es_terminal and self.fecha_hora < timezone.now()

    @property
    def proximo_a_vencer(self):
        ahora = timezone.now()
        limite = ahora + timedelta(days=7)
        return (
            not self.es_terminal
            and ahora <= self.fecha_hora <= limite
        )

    @property
    def realizado_fuera_de_plazo(self):
        return bool(
            self.fecha_realizacion
            and self.fecha_realizacion > self.fecha_hora
        )

    @property
    def esta_cerrado(self):
        return self.estado in (self.Estado.CERRADO, self.Estado.NO_APLICA)

    @property
    def es_terminal(self):
        return self.estado in (
            self.Estado.REALIZADO, self.Estado.CERRADO, self.Estado.NO_APLICA,
        )


class HistorialCompromiso(models.Model):
    """Audita cambios de estado, responsable y plazo del compromiso."""

    compromiso = models.ForeignKey(
        Compromiso,
        on_delete=models.CASCADE,
        related_name='historial',
        verbose_name='Compromiso',
    )
    campo = models.CharField('Campo modificado', max_length=40)
    valor_anterior = models.TextField('Valor anterior', blank=True)
    valor_nuevo = models.TextField('Valor nuevo', blank=True)
    motivo = models.TextField('Motivo del cambio', blank=True)
    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cambios_compromiso',
        verbose_name='Modificado por',
    )
    creado = models.DateTimeField('Fecha del cambio', auto_now_add=True)

    class Meta:
        verbose_name = 'Cambio de compromiso'
        verbose_name_plural = 'Historial de compromisos'
        ordering = ['-creado']

    def __str__(self):
        return f'{self.compromiso}: {self.campo} ({self.creado:%Y-%m-%d %H:%M})'

    def save(self, *args, **kwargs):
        validar_periodo_abierto(
            self.compromiso.fecha_hora,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        return super().save(*args, **kwargs)


class SolicitudAmpliacion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    compromiso = models.ForeignKey(Compromiso, on_delete=models.PROTECT, related_name='solicitudes_ampliacion')
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ampliaciones_solicitadas')
    plazo_anterior = models.DateTimeField()
    plazo_propuesto = models.DateTimeField()
    motivo = models.TextField()
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    creado = models.DateTimeField(auto_now_add=True)
    decidido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='ampliaciones_decididas')
    fecha_decision = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado']
        constraints = [models.UniqueConstraint(fields=['compromiso'], condition=models.Q(estado='pendiente'), name='una_ampliacion_pendiente_por_compromiso')]

    def save(self, *args, **kwargs):
        validar_periodo_abierto(
            self.compromiso.fecha_hora,
            'No se puede ampliar un compromiso de un período cerrado.',
        )
        return super().save(*args, **kwargs)
