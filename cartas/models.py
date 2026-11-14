from pathlib import Path
import uuid

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
        DERIVADA = 'derivada', 'Derivada'
        APROBADA = 'aprobada', 'Aprobada'
        FINALIZADA = 'finalizada', 'Finalizada'
        NO_APLICA = 'no_aplica', 'No aplica'

    codigo = models.CharField('Código', max_length=30, unique=True, editable=False, blank=True)
    remitente = models.CharField('Remitente', max_length=180, blank=True)
    destinatario = models.CharField('Destinatario', max_length=180, blank=True)
    telefono = models.CharField('Teléfono', max_length=30, blank=True)
    asunto = models.CharField('Asunto', max_length=200)
    contenido = models.TextField('Contenido de la carta')
    respuesta = models.TextField('Respuesta', blank=True)
    observaciones = models.TextField('Observaciones', blank=True)
    area_derivada = models.CharField('Área derivada', max_length=160, blank=True)
    fecha_actividad = models.DateField('Fecha de actividad o respuesta', null=True, blank=True)
    fecha_cierre = models.DateField('Fecha de cierre', null=True, blank=True)
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
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_ingreso,
            'No se puede crear ni modificar una carta de un período cerrado.',
        )
        if self.estado in (self.Estado.RESPONDIDA, self.Estado.APROBADA) and not self.respuesta.strip():
            raise ValidationError({'respuesta': 'Debe registrar el pronunciamiento antes de aprobar la carta.'})
        if self.estado in (self.Estado.CERRADA, self.Estado.FINALIZADA) and not self.fecha_cierre:
            original = type(self).objects.filter(pk=self.pk).values('estado').first() if self.pk else None
            if not original or original['estado'] != self.estado:
                raise ValidationError({'fecha_cierre': 'Indique la fecha de cierre de la carta.'})
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

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_ingreso,
            'No se puede eliminar una carta de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


class HistorialCarta(models.Model):
    carta = models.ForeignKey(Carta, on_delete=models.PROTECT, related_name='historial')
    accion = models.CharField('Acción', max_length=40)
    estado_anterior = models.CharField(max_length=20, blank=True)
    estado_nuevo = models.CharField(max_length=20, blank=True)
    campo = models.CharField('Campo', max_length=50, blank=True)
    valor_anterior = models.TextField('Valor anterior', blank=True)
    valor_nuevo = models.TextField('Valor nuevo', blank=True)
    motivo = models.TextField('Motivo u observación', blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='historial_cartas',
    )
    creado_en = models.DateTimeField('Fecha de seguimiento', auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']
        verbose_name = 'Seguimiento de carta'
        verbose_name_plural = 'Historial de cartas'

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.carta.fecha_ingreso,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.carta.fecha_ingreso,
            'No se puede eliminar seguimiento de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


def ruta_documento_carta(instance, filename):
    extension = Path(filename).suffix.lower()[:10]
    return f'cartas/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}'


class DocumentoCarta(models.Model):
    carta = models.ForeignKey(Carta, on_delete=models.PROTECT, related_name='documentos')
    archivo = models.FileField('Documento', upload_to=ruta_documento_carta)
    descripcion = models.CharField('Descripción', max_length=200, blank=True)
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='documentos_cartas_subidos',
    )
    creado_en = models.DateTimeField('Fecha de carga', auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']
        verbose_name = 'Documento de carta'
        verbose_name_plural = 'Documentos de cartas'

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.carta.fecha_ingreso,
            'No se puede agregar ni modificar documentos de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.carta.fecha_ingreso,
            'No se puede eliminar documentos de un período cerrado.',
        )
        return super().delete(*args, **kwargs)
