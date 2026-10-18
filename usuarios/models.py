from django.conf import settings
from django.db import models


class Delegacion(models.Model):
    """Unidad territorial o delegación municipal."""

    codigo = models.CharField('Código', max_length=30, unique=True)
    nombre = models.CharField('Nombre', max_length=150, unique=True)
    direccion = models.CharField('Dirección', max_length=200, blank=True)
    comuna = models.CharField('Comuna', max_length=80, blank=True)
    activa = models.BooleanField('Estado activo', default=True)

    class Meta:
        verbose_name = 'Delegación'
        verbose_name_plural = 'Delegaciones'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    @property
    def estado_display(self):
        return 'Activo' if self.activa else 'Inactivo'


class Rol(models.Model):
    """Rol institucional con permisos y alcance."""

    class Alcance(models.TextChoices):
        GLOBAL = 'global', 'Global'
        DELEGACION = 'delegacion', 'Delegación'

    codigo = models.CharField('Código', max_length=30, unique=True)
    nombre = models.CharField('Nombre', max_length=80, unique=True)
    descripcion = models.TextField('Descripción', blank=True)
    permisos = models.JSONField('Permisos', default=dict, blank=True)
    alcance = models.CharField(
        'Alcance',
        max_length=20,
        choices=Alcance.choices,
        default=Alcance.DELEGACION,
    )
    activo = models.BooleanField('Estado activo', default=True)

    class Meta:
        verbose_name = 'Rol'
        verbose_name_plural = 'Roles'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    @property
    def estado_display(self):
        return 'Activo' if self.activo else 'Inactivo'


def permisos_por_codigo(codigo):
    catalogo = True
    return {
        'usuarios': codigo == 'administrador',
        'roles': codigo == 'administrador',
        'delegaciones': codigo in ('administrador', 'coordinador'),
        'catalogos': codigo in ('administrador', 'coordinador'),
        'atenciones': True,
        'auditoria': codigo in ('administrador', 'coordinador'),
        'actividades': True,
        'evidencias': True,
        'agenda': True,
        'validar_evidencias': codigo in ('administrador', 'coordinador', 'verificador'),
        'catalogo_completo': catalogo and codigo in ('administrador', 'coordinador'),
    }


class Perfil(models.Model):
    """Extiende al usuario de Django con rol y delegaciones."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
        verbose_name='Usuario',
    )
    rol = models.ForeignKey(
        Rol,
        on_delete=models.PROTECT,
        related_name='perfiles',
        verbose_name='Rol',
        null=True,
        blank=True,
    )
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfiles',
        verbose_name='Delegación activa por defecto',
    )
    delegaciones = models.ManyToManyField(
        Delegacion,
        blank=True,
        related_name='perfiles_autorizados',
        verbose_name='Delegaciones autorizadas',
    )
    cargo = models.CharField('Cargo', max_length=120, blank=True)
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfiles'
        ordering = ['usuario__username']

    def __str__(self):
        return f'{self.usuario.get_full_name() or self.usuario.username} ({self.rol})'

    @property
    def rol_codigo(self):
        if self.rol_id:
            return self.rol.codigo
        return None

    @property
    def estado_display(self):
        return 'Activo' if self.activo and self.usuario.is_active else 'Inactivo'

    @property
    def delegaciones_display(self):
        return ', '.join(self.delegaciones.values_list('nombre', flat=True))


class CodigoRecuperacion(models.Model):
    """Código temporal para restablecer contraseña."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='codigos_recuperacion',
    )
    codigo_hash = models.CharField(max_length=128)
    creado = models.DateTimeField(auto_now_add=True)
    expira = models.DateTimeField()
    intentos = models.PositiveSmallIntegerField(default=0)
    usado = models.BooleanField(default=False)

    class Meta:
        ordering = ['-creado']

    def __str__(self):
        return f'Recuperación {self.usuario_id} ({self.pk})'
