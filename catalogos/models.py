from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from django.conf import settings

from usuarios.codigos import guardar_con_codigo_automatico
from usuarios.models import Delegacion


class ItemMeta(models.Model):
    codigo = models.CharField('Código', max_length=30, unique=True)
    nombre = models.CharField('Nombre', max_length=150)
    descripcion = models.TextField('Descripción', blank=True)
    activo = models.BooleanField('Estado activo', default=True)

    class Meta:
        verbose_name = 'Ítem / meta'
        verbose_name_plural = 'Ítems y metas'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    @property
    def estado_display(self):
        return 'Activo' if self.activo else 'Inactivo'


class TipoAtencion(models.Model):
    codigo = models.CharField('Código', max_length=30, unique=True)
    nombre = models.CharField('Nombre', max_length=150)
    descripcion = models.TextField('Descripción', blank=True)
    activo = models.BooleanField('Estado activo', default=True)
    es_general = models.BooleanField('Catálogo general', default=True)
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tipos_atencion',
        verbose_name='Delegación',
    )

    class Meta:
        verbose_name = 'Tipo de atención'
        verbose_name_plural = 'Tipos de atención'
        ordering = ['codigo']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(es_general=True, delegacion__isnull=True)
                    | Q(es_general=False, delegacion__isnull=False)
                ),
                name='tipoatencion_alcance_valido',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    def clean(self):
        super().clean()
        if self.es_general and self.delegacion_id:
            raise ValidationError({'delegacion': 'Una categoría general no puede tener delegación.'})
        if not self.es_general and not self.delegacion_id:
            raise ValidationError({'delegacion': 'Una categoría de delegación requiere una delegación.'})
        if (
            not self.es_general
            and self.pk
            and self.subatenciones.exclude(
                es_general=False,
                delegacion_id=self.delegacion_id,
            ).exists()
        ):
            raise ValidationError(
                {
                    'delegacion':
                        'La categoría tiene subcategorías incompatibles con el alcance solicitado.'
                }
            )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    @property
    def estado_display(self):
        return 'Activo' if self.activo else 'Inactivo'


class SubAtencion(models.Model):
    codigo = models.CharField('Código', max_length=30, unique=True)
    nombre = models.CharField('Nombre', max_length=150)
    tipo = models.ForeignKey(
        TipoAtencion,
        on_delete=models.PROTECT,
        related_name='subatenciones',
        verbose_name='Tipo de atención',
    )
    activo = models.BooleanField('Estado activo', default=True)
    es_general = models.BooleanField('Subcategoría general', default=True)
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='subatenciones',
        verbose_name='Delegación',
    )

    class Meta:
        verbose_name = 'Subatención'
        verbose_name_plural = 'Subatenciones'
        ordering = ['codigo']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(es_general=True, delegacion__isnull=True)
                    | Q(es_general=False, delegacion__isnull=False)
                ),
                name='subatencion_alcance_valido',
            ),
        ]

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    def clean(self):
        super().clean()
        errors = {}
        if self.es_general and self.delegacion_id:
            errors['delegacion'] = 'Una subcategoría general no puede tener delegación.'
        elif not self.es_general and not self.delegacion_id:
            errors['delegacion'] = 'Una subcategoría de delegación requiere una delegación.'

        if self.tipo_id and not errors:
            tipo = self.tipo
            if not tipo.es_general and (
                self.es_general or self.delegacion_id != tipo.delegacion_id
            ):
                errors['delegacion'] = (
                    'La subcategoría debe pertenecer a la misma delegación que su categoría.'
                )
            elif (
                self._state.adding
                and self.es_general
                and (not tipo.activo or tipo.delegacion_id is not None)
            ):
                errors['tipo'] = (
                    'Una subcategoría general requiere una categoría general activa.'
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        if self._state.adding:
            def guardar(**sobrescrituras):
                save_kwargs = kwargs.copy()
                save_kwargs.update(sobrescrituras)
                return super(SubAtencion, self).save(*args, **save_kwargs)

            return guardar_con_codigo_automatico(self, 'SUB', guardar)

        codigo_original = type(self).objects.filter(pk=self.pk).values_list(
            'codigo',
            flat=True,
        ).first()
        if codigo_original is not None:
            self.codigo = codigo_original
        return super().save(*args, **kwargs)

    @property
    def estado_display(self):
        return 'Activo' if self.activo else 'Inactivo'


class SolicitudCatalogoGeneral(models.Model):
    class Tipo(models.TextChoices):
        CATEGORIA = 'categoria', 'Categoría'
        SUBCATEGORIA = 'subcategoria', 'Subcategoría'

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    tipo_solicitud = models.CharField(
        'Tipo de solicitud',
        max_length=20,
        choices=Tipo.choices,
    )
    codigo = models.CharField('Código solicitado', max_length=30)
    nombre = models.CharField('Nombre solicitado', max_length=150)
    descripcion = models.TextField('Descripción', blank=True)
    categoria_padre = models.ForeignKey(
        TipoAtencion,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='solicitudes_subatencion_general',
        verbose_name='Categoría padre',
    )
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='solicitudes_catalogo_general',
        verbose_name='Solicitado por',
    )
    delegacion_solicitante = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='solicitudes_catalogo_general',
        verbose_name='Delegación solicitante',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='decisiones_solicitudes_catalogo',
        verbose_name='Decidido por',
    )
    fecha_decision = models.DateTimeField('Fecha de decisión', null=True, blank=True)
    motivo_decision = models.TextField('Motivo de decisión', blank=True)
    creado = models.DateTimeField('Fecha de solicitud', auto_now_add=True)

    class Meta:
        verbose_name = 'Solicitud de catálogo general'
        verbose_name_plural = 'Solicitudes de catálogos generales'
        ordering = ['-creado']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(tipo_solicitud='categoria', categoria_padre__isnull=True)
                    | Q(tipo_solicitud='subcategoria', categoria_padre__isnull=False)
                ),
                name='solicitud_catalogo_padre_valido',
            ),
            models.CheckConstraint(
                condition=(
                    Q(estado='pendiente', decidido_por__isnull=True, fecha_decision__isnull=True)
                    | Q(
                        estado__in=('aprobada', 'rechazada'),
                        decidido_por__isnull=False,
                        fecha_decision__isnull=False,
                    )
                ),
                name='solicitud_catalogo_decision_valida',
            ),
        ]

    def __str__(self):
        return f'{self.get_tipo_solicitud_display()}: {self.nombre} ({self.get_estado_display()})'

    def clean(self):
        super().clean()
        if self.tipo_solicitud == self.Tipo.CATEGORIA and self.categoria_padre_id:
            raise ValidationError({'categoria_padre': 'Una solicitud de categoría no tiene categoría padre.'})
        if self.tipo_solicitud == self.Tipo.SUBCATEGORIA:
            if not self.categoria_padre_id:
                raise ValidationError({'categoria_padre': 'La subcategoría requiere una categoría padre.'})
            if self._state.adding and (
                not self.categoria_padre.activo
                or not self.categoria_padre.es_general
                or self.categoria_padre.delegacion_id is not None
            ):
                raise ValidationError(
                    {
                        'categoria_padre':
                            'Una subcategoría general requiere una categoría general activa.'
                    }
                )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
