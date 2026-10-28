from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from usuarios.models import Delegacion


class Compromiso(models.Model):
    """Compromiso municipal con seguimiento, responsable y actividades asociadas."""

    class Estado(models.TextChoices):
        INGRESADO = 'ingresado', 'Ingresado'
        PENDIENTE = 'pendiente', 'Pendiente'
        EN_PROCESO = 'en_proceso', 'En proceso'
        REALIZADO = 'realizado', 'Realizado'

    titulo = models.CharField('Título', max_length=200)
    descripcion = models.TextField('Descripción', blank=True)
    solicitante = models.CharField('Solicitante', max_length=180, blank=True)
    area_apoyo = models.CharField('Área de apoyo', max_length=120, blank=True)
    observaciones = models.TextField('Observaciones', blank=True)
    fecha_hora = models.DateTimeField('Fecha y hora')
    fecha_realizacion = models.DateTimeField('Fecha de realización', null=True, blank=True)
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

    def __str__(self):
        return self.titulo

    @property
    def esta_vencido(self):
        return self.estado != self.Estado.REALIZADO and self.fecha_hora < timezone.now()

    @property
    def proximo_a_vencer(self):
        ahora = timezone.now()
        limite = ahora + timedelta(days=7)
        return (
            self.estado != self.Estado.REALIZADO
            and ahora <= self.fecha_hora <= limite
        )

    @property
    def realizado_fuera_de_plazo(self):
        return bool(
            self.fecha_realizacion
            and self.fecha_realizacion > self.fecha_hora
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
