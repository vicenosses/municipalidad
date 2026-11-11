from django.db import models

# Create your models here.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Delegacion, Territorio, Vecino


class GestionSocial(models.Model):
    class Estado(models.TextChoices):
        REGISTRADA = 'registrada', 'Registrada'
        EN_PROCESO = 'en_proceso', 'En proceso'
        PENDIENTE_ANTECEDENTES = 'pendiente_antecedentes', 'Pendiente de antecedentes'
        DERIVADA = 'derivada', 'Derivada'
        CERRADA = 'cerrada', 'Cerrada'

    class Tipo(models.TextChoices):
        ORIENTACION = 'orientacion', 'Orientación'
        APOYO = 'apoyo', 'Apoyo social'
        DERIVACION = 'derivacion', 'Derivación'
        VISITA = 'visita', 'Visita'
        BENEFICIO = 'beneficio', 'Beneficio'
        OTRO = 'otro', 'Otro'

    codigo = models.CharField('Código', max_length=30, unique=True, editable=False, blank=True)
    titulo = models.CharField('Título', max_length=200)
    tipo = models.CharField('Tipo de gestión', max_length=20, choices=Tipo.choices, default=Tipo.ORIENTACION)
    descripcion = models.TextField('Antecedentes de la gestión')
    vecino = models.ForeignKey(
        Vecino, on_delete=models.PROTECT, null=True, blank=True,
        related_name='gestiones_sociales',
    )
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='gestiones_sociales')
    territorio = models.ForeignKey(
        Territorio, on_delete=models.PROTECT, null=True, blank=True,
        related_name='gestiones_sociales',
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='gestiones_sociales',
    )
    fecha_ingreso = models.DateField('Fecha de ingreso', default=timezone.localdate)
    fecha_compromiso = models.DateField('Fecha de compromiso', null=True, blank=True)
    estado = models.CharField('Estado', max_length=30, choices=Estado.choices, default=Estado.REGISTRADA)
    ingresa_al_tubo = models.BooleanField('Incluir en el tubo', default=False)
    activo = models.BooleanField('Activo', default=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gestiones_sociales_creadas',
    )
    creado_en = models.DateTimeField('Creado', auto_now_add=True)
    actualizado_en = models.DateTimeField('Actualizado', auto_now=True)

    class Meta:
        ordering = ['-fecha_ingreso', '-pk']
        verbose_name = 'Gestión social'
        verbose_name_plural = 'Gestiones sociales'
        indexes = [
            models.Index(fields=['delegacion', 'estado', 'activo']),
            models.Index(fields=['responsable', 'estado']),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.titulo}'

    def clean(self):
        super().clean()
        if self.territorio_id and self.delegacion_id != self.territorio.delegacion_id:
            raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación.'})
        if self.vecino_id and self.territorio_id and self.vecino.territorio_id != self.territorio_id:
            raise ValidationError({'vecino': 'El vecino debe pertenecer al territorio seleccionado.'})
        if self.fecha_compromiso and self.fecha_ingreso and self.fecha_compromiso < self.fecha_ingreso:
            raise ValidationError({'fecha_compromiso': 'La fecha de compromiso no puede ser anterior al ingreso.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(GestionSocial, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'GES', guardar)
        return super().save(*args, **kwargs)
