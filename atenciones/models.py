from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from catalogos.models import SubAtencion, TipoAtencion
from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Delegacion, Territorio


class AtencionCiudadana(models.Model):
    class Estado(models.TextChoices):
        REGISTRADA = 'registrada', 'Pendiente'
        EN_PROCESO = 'en_proceso', 'En proceso'
        COMPLETADA = 'completada', 'Completada'
        CERRADA = 'cerrada', 'Cerrada'
        NO_APLICA = 'no_aplica', 'No aplica'

    titulo = models.CharField('Título', max_length=200)
    fecha = models.DateField('Fecha de la actividad')
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.REGISTRADA,
    )
    activo = models.BooleanField('Habilitada', default=True)
    origen = models.CharField('Origen', max_length=180, blank=True)
    avance = models.PositiveSmallIntegerField('Avance (%)', default=0)
    apoyo_requerido = models.TextField('Apoyo requerido', blank=True)
    resultado = models.TextField('Resultado', blank=True)
    fecha_completada = models.DateField('Fecha de término', null=True, blank=True)
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
    territorio = models.ForeignKey('usuarios.Territorio', on_delete=models.PROTECT,
                                  related_name='actividades', null=True, blank=True,
                                  verbose_name='Territorio')
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
        if self.avance > 100:
            raise ValidationError({'avance': 'El avance debe estar entre 0 y 100.'})
        fecha_completada_anterior = self.fecha_completada
        if self.estado in (self.Estado.COMPLETADA, self.Estado.CERRADA) and not self.fecha_completada:
            self.fecha_completada = timezone.localdate()
        elif self.estado not in (self.Estado.COMPLETADA, self.Estado.CERRADA):
            self.fecha_completada = None
        if fecha_completada_anterior != self.fecha_completada and kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'fecha_completada'}
        from sgr.models import Periodo

        if Periodo.objects.filter(
            cerrado=True,
            fecha_inicio__lte=self.fecha,
            fecha_fin__gte=self.fecha,
        ).exists():
            raise ValidationError('No se puede crear ni modificar una Actividad de un período cerrado.')
        if not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(
                'delegacion_id',
            ).first()
            if original:
                self.delegacion_id = original['delegacion_id']
        if self.territorio_id:
            from usuarios.models import Territorio
            if not Territorio.objects.filter(pk=self.territorio_id, delegacion_id=self.delegacion_id).exists():
                raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación de la actividad.'})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha,
            'No se puede eliminar una actividad de un período cerrado.',
        )
        return super().delete(*args, **kwargs)

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
        from evidencias.consultas import evidencias_vigentes_actividad

        evidencias = getattr(self, '_prefetched_objects_cache', {}).get('evidencias')
        if evidencias is None:
            estados = set(evidencias_vigentes_actividad(self.pk).values_list('estado', flat=True))
        else:
            reemplazadas = {evidencia.reemplaza_id for evidencia in evidencias if evidencia.reemplaza_id}
            estados = {
                evidencia.estado for evidencia in evidencias
                if evidencia.pk not in reemplazadas
            }
        if not estados:
            return 'sin_evidencia'
        if 'rechazada' in estados:
            return 'rechazada'
        if 'pendiente' in estados:
            return 'pendiente'
        return 'aprobada'

    def puede_cerrar_por_evidencias(self):
        from evidencias.consultas import puede_cerrar_actividad_por_evidencias

        return puede_cerrar_actividad_por_evidencias(self.pk)

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


class ReconocimientoCiudadano(models.Model):
    class Tipo(models.TextChoices):
        RECLAMO = 'reclamo', 'Reclamo'
        FELICITACION = 'felicitacion', 'Felicitación'

    codigo = models.CharField(max_length=30, unique=True, editable=False, blank=True)
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    titulo = models.CharField('Asunto', max_length=200)
    descripcion = models.TextField('Detalle', blank=True)
    fecha = models.DateField('Fecha del registro', default=timezone.localdate)
    vecino = models.ForeignKey(
        'usuarios.Vecino', on_delete=models.PROTECT, null=True, blank=True,
        related_name='reconocimientos_ciudadanos',
    )
    delegacion = models.ForeignKey(
        Delegacion, on_delete=models.PROTECT, related_name='reconocimientos_ciudadanos',
    )
    territorio = models.ForeignKey(
        Territorio, on_delete=models.PROTECT, null=True, blank=True,
        related_name='reconocimientos_ciudadanos',
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='reconocimientos_ciudadanos_responsable',
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reconocimientos_ciudadanos_creados',
    )
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha', '-pk']
        verbose_name = 'Reclamo o felicitación'
        verbose_name_plural = 'Reclamos y felicitaciones'
        indexes = [
            models.Index(fields=['delegacion', 'tipo', 'fecha']),
            models.Index(fields=['responsable', 'fecha']),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.get_tipo_display()}: {self.titulo}'

    def clean(self):
        super().clean()
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha,
            'No se puede crear ni modificar un registro de un período cerrado.',
        )
        if self.territorio_id and self.territorio.delegacion_id != self.delegacion_id:
            raise ValidationError({'territorio': 'El territorio debe pertenecer a la delegación.'})
        if self.vecino_id:
            if self.vecino.territorio.delegacion_id != self.delegacion_id:
                raise ValidationError({'vecino': 'El vecino debe pertenecer a la delegación seleccionada.'})
            if self.territorio_id and self.vecino.territorio_id != self.territorio_id:
                raise ValidationError({'vecino': 'El vecino debe pertenecer al territorio seleccionado.'})
        if self.responsable_id and self.delegacion_id:
            from usuarios.models import Perfil

            if not Perfil.objects.filter(
                usuario_id=self.responsable_id,
                activo=True,
            ).filter(
                Q(delegaciones__pk=self.delegacion_id)
                | Q(delegacion_id=self.delegacion_id),
            ).exists():
                raise ValidationError({
                    'responsable': 'El responsable debe estar activo y autorizado en la delegación.',
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(ReconocimientoCiudadano, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'RCF', guardar)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.fecha,
            'No se puede eliminar un registro de un período cerrado.',
        )
        return super().delete(*args, **kwargs)


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

    def save(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.actividad.fecha,
            'No se puede agregar ni modificar historial de un período cerrado.',
        )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from sgr.periodos import validar_periodo_abierto

        validar_periodo_abierto(
            self.actividad.fecha,
            'No se puede eliminar historial de un período cerrado.',
        )
        return super().delete(*args, **kwargs)
