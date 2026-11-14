import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Delegacion, Territorio, Vecino


def ruta_documento_social(instance, filename):
    extension = filename.rsplit('.', 1)[-1].lower()[:10] if '.' in filename else ''
    return f'gestiones-sociales/{timezone.now():%Y/%m}/{uuid.uuid4().hex}' + (
        f'.{extension}' if extension else ''
    )


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
    subtipo = models.CharField('Subtipo de atención', max_length=120, blank=True)
    descripcion = models.TextField('Antecedentes de la gestión')
    resultado = models.TextField('Resultado', blank=True)
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
    asignacion_meta = models.ForeignKey(
        'sgr.AsignacionMeta', on_delete=models.PROTECT, null=True, blank=True,
        related_name='gestiones_sociales',
    )
    fecha_ingreso = models.DateField('Fecha de ingreso', default=timezone.localdate)
    fecha_compromiso = models.DateField('Fecha de compromiso', null=True, blank=True)
    fecha_cierre = models.DateField('Fecha de cierre', null=True, blank=True)
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
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_ingreso,
            'No se puede crear ni modificar una gestión social de un período cerrado.',
        )
        if self.vecino_id is None:
            raise ValidationError({'vecino': 'Seleccione al beneficiario de la gestión social.'})
        if self.territorio_id and self.delegacion_id != self.territorio.delegacion_id:
            raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación.'})
        if self.vecino_id and self.territorio_id and self.vecino.territorio_id != self.territorio_id:
            raise ValidationError({'vecino': 'El vecino debe pertenecer al territorio seleccionado.'})
        if self.fecha_compromiso and self.fecha_ingreso and self.fecha_compromiso < self.fecha_ingreso:
            raise ValidationError({'fecha_compromiso': 'La fecha de compromiso no puede ser anterior al ingreso.'})
        if self.asignacion_meta_id and (
            self.asignacion_meta.funcionario_id != self.responsable_id
            or self.asignacion_meta.meta.delegacion_id != self.delegacion_id
        ):
            raise ValidationError({'asignacion_meta': 'La meta asignada debe corresponder al responsable y delegación.'})
        if self.estado == self.Estado.CERRADA and not self.fecha_cierre:
            original = type(self).objects.filter(pk=self.pk).values('estado').first() if self.pk else None
            if not original or original['estado'] != self.estado:
                raise ValidationError({'fecha_cierre': 'Indique la fecha de cierre de la gestión.'})
        if self.estado != self.Estado.CERRADA and self.fecha_cierre:
            raise ValidationError({'fecha_cierre': 'Solo una gestión cerrada puede tener fecha de cierre.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(GestionSocial, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'GES', guardar)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha_ingreso,
            'No se puede eliminar una gestión social de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


class HistorialGestionSocial(models.Model):
    gestion = models.ForeignKey(GestionSocial, on_delete=models.PROTECT, related_name='historial')
    accion = models.CharField('Acción', max_length=40)
    estado_anterior = models.CharField(max_length=30, blank=True)
    estado_nuevo = models.CharField(max_length=30, blank=True)
    motivo = models.TextField('Observación', blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='historial_gestiones_sociales',
    )
    creado_en = models.DateTimeField('Fecha de seguimiento', auto_now_add=True)

    class Meta:
        ordering = ['-creado_en', '-pk']
        verbose_name = 'Seguimiento social'
        verbose_name_plural = 'Historial de gestiones sociales'

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.gestion.fecha_ingreso,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.gestion.fecha_ingreso,
            'No se puede eliminar seguimiento de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


class SeguimientoGestionSocial(models.Model):
    class Tipo(models.TextChoices):
        VISITA = 'visita', 'Visita'
        ACCION = 'accion', 'Acción'
        DERIVACION = 'derivacion', 'Derivación'
        INFORME = 'informe', 'Informe'
        BENEFICIO = 'beneficio', 'Beneficio'

    gestion = models.ForeignKey(GestionSocial, on_delete=models.PROTECT, related_name='seguimientos')
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    fecha = models.DateField('Fecha de la gestión', default=timezone.localdate)
    area_institucion = models.CharField('Área o institución', max_length=180, blank=True)
    beneficio = models.CharField('Beneficio', max_length=180, blank=True)
    resultado = models.TextField('Resultado', blank=True)
    observaciones = models.TextField('Observaciones', blank=True)
    evidencia = models.FileField('Documento de respaldo', upload_to=ruta_documento_social, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='seguimientos_sociales_registrados',
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        validar_periodo_abierto(
            self.gestion.fecha_ingreso,
            'No se puede agregar ni modificar seguimiento de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.gestion.fecha_ingreso,
            'No se puede eliminar seguimiento de un período cerrado.',
        )
        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['-fecha', '-pk']
        verbose_name = 'Acción de gestión social'
        verbose_name_plural = 'Acciones de gestiones sociales'
