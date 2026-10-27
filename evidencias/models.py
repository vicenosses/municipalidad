import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from atenciones.models import AtencionCiudadana


def ruta_evidencia(instance, filename):
    """Guarda con nombre aleatorio y extensión permitida, sin usar el nombre del cliente."""
    extension = Path(filename).suffix.lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.webm'}:
        extension = '.bin'
    return f'evidencias/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}'


class Evidencia(models.Model):
    """Archivo de respaldo vinculado a un registro, atención o compromiso de agenda."""

    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    atencion = models.ForeignKey(
        AtencionCiudadana,
        on_delete=models.PROTECT,
        related_name='evidencias',
        verbose_name='Atención ciudadana',
        null=True,
        blank=True,
    )
    compromiso = models.ForeignKey(
        'agenda.Compromiso',
        on_delete=models.PROTECT,
        related_name='evidencias',
        verbose_name='Compromiso de agenda',
        null=True,
        blank=True,
    )
    descripcion = models.CharField('Descripción', max_length=240, blank=True)
    archivo = models.FileField('Archivo', upload_to=ruta_evidencia)
    codigo_respaldo = models.UUIDField(
        'Código de respaldo',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    identificador = models.CharField(
        'Identificador',
        max_length=160,
        unique=True,
        editable=False,
        blank=True,
    )
    tipo_archivo = models.CharField(
        'Tipo de archivo',
        max_length=10,
        choices=(('imagen', 'Imagen'), ('video', 'Video')),
        default='imagen',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='evidencias_subidas',
        verbose_name='Subido por',
    )
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evidencias_validadas',
        verbose_name='Validado por',
    )
    comentario_validacion = models.TextField('Comentario de validación', blank=True)
    fecha_subida = models.DateTimeField('Fecha de subida', auto_now_add=True)
    fecha_validacion = models.DateTimeField('Fecha de validación', null=True, blank=True)

    class Meta:
        verbose_name = 'Evidencia'
        verbose_name_plural = 'Evidencias'
        ordering = ['-fecha_subida']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        atencion__isnull=False,
                        compromiso__isnull=True,
                    )
                    | models.Q(
                        atencion__isnull=True,
                        compromiso__isnull=False,
                    )
                ),
                name='evidencia_origen_valido',
            ),
        ]

    def __str__(self):
        return self.identificador or str(self.codigo_respaldo)

    @property
    def content_type(self):
        extension = Path(self.archivo.name).suffix.lower()
        return {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.mp4': 'video/mp4',
            '.webm': 'video/webm',
        }.get(extension, 'application/octet-stream')

    def clean(self):
        super().clean()
        if bool(self.atencion_id) == bool(self.compromiso_id):
            raise ValidationError('La evidencia debe pertenecer a una actividad o a un compromiso, pero no a ambos.')

    @property
    def origen(self):
        if self.atencion_id:
            return 'Actividad'
        if self.compromiso_id:
            return 'Agenda'
        return ''

    def save(self, *args, **kwargs):
        if not self.identificador and self.subido_por_id:
            extension = Path(self.archivo.name).suffix.lower()
            self.tipo_archivo = 'video' if extension in {'.mp4', '.webm'} else 'imagen'
            nombre = slugify(self.subido_por.get_username())[:32] or f'usuario-{self.subido_por_id}'
            fecha = timezone.localtime(timezone.now()).strftime('%Y%m%d')
            self.identificador = f'{fecha}_{nombre}_{self.tipo_archivo}_{uuid.uuid4().hex}'
        super().save(*args, **kwargs)
