from django.db import models


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

    class Meta:
        verbose_name = 'Tipo de atención'
        verbose_name_plural = 'Tipos de atención'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

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

    class Meta:
        verbose_name = 'Subatención'
        verbose_name_plural = 'Subatenciones'
        ordering = ['codigo']

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    @property
    def estado_display(self):
        return 'Activo' if self.activo else 'Inactivo'
