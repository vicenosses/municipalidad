from django.conf import settings
from django.db import models


class Delegacion(models.Model):
    """Unidad territorial o delegación municipal."""

    nombre = models.CharField('Nombre', max_length=150, unique=True)
    activa = models.BooleanField('Activa', default=True)

    class Meta:
        verbose_name = 'Delegación'
        verbose_name_plural = 'Delegaciones'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Perfil(models.Model):
    """Extiende al usuario de Django con rol y delegación."""

    class Rol(models.TextChoices):
        ADMINISTRADOR = 'administrador', 'Administrador'
        COORDINADOR = 'coordinador', 'Coordinador'
        FUNCIONARIO = 'funcionario', 'Funcionario'
        VERIFICADOR = 'verificador', 'Verificador'
        DELEGADO = 'delegado', 'Delegado'

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
        verbose_name='Usuario',
    )
    rol = models.CharField(
        'Rol',
        max_length=20,
        choices=Rol.choices,
        default=Rol.FUNCIONARIO,
    )
    delegacion = models.ForeignKey(
        Delegacion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfiles',
        verbose_name='Delegación',
    )
    cargo = models.CharField('Cargo', max_length=120, blank=True)
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfiles'
        ordering = ['usuario__username']

    def __str__(self):
        return f'{self.usuario.get_full_name() or self.usuario.username} ({self.get_rol_display()})'
