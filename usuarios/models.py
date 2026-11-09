from django.conf import settings
from django.db import models

from usuarios.codigos import guardar_con_codigo_automatico


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

    def save(self, *args, **kwargs):
        if self._state.adding:
            def guardar(**sobrescrituras):
                save_kwargs = kwargs.copy()
                save_kwargs.update(sobrescrituras)
                return super(Delegacion, self).save(*args, **save_kwargs)

            return guardar_con_codigo_automatico(self, 'DEL', guardar)

        codigo_original = type(self).objects.filter(pk=self.pk).values_list(
            'codigo',
            flat=True,
        ).first()
        if codigo_original is not None:
            self.codigo = codigo_original
        return super().save(*args, **kwargs)

    @property
    def estado_display(self):
        return 'Activo' if self.activa else 'Inactivo'


class Territorio(models.Model):
    codigo = models.CharField('Código', max_length=30, unique=True, editable=False)
    nombre = models.CharField('Nombre', max_length=150)
    descripcion = models.TextField('Descripción o sector', blank=True)
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='territorios')
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        ordering = ['-activo', 'nombre', 'pk']
        constraints = [models.UniqueConstraint(fields=['delegacion', 'nombre'], name='territorio_nombre_delegacion_unico')]

    def __str__(self):
        return f'{self.codigo} — {self.nombre}'

    def save(self, *args, **kwargs):
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(Territorio, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'TER', guardar)
        original = type(self).objects.filter(pk=self.pk).values_list('codigo', flat=True).first()
        if original is not None:
            self.codigo = original
        return super().save(*args, **kwargs)


class IntentosIngreso(models.Model):
    identificador_hash = models.CharField(max_length=64, unique=True)
    intentos = models.PositiveIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    actualizado = models.DateTimeField(auto_now=True)


class Vecino(models.Model):
    rut = models.CharField('RUT', max_length=20, unique=True)
    nombres = models.CharField('Nombres', max_length=150)
    apellidos = models.CharField('Apellidos', max_length=150)
    telefono = models.CharField('Teléfono', max_length=30, blank=True)
    correo = models.EmailField('Correo', blank=True)
    direccion = models.CharField('Dirección', max_length=200, blank=True)
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='vecinos')
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        ordering = ['-activo', 'apellidos', 'nombres']

    def __str__(self):
        return f'{self.nombres} {self.apellidos}'


class JuntaVecinos(models.Model):
    codigo = models.CharField('Código', max_length=30, unique=True, editable=False)
    nombre = models.CharField('Nombre', max_length=150)
    direccion = models.CharField('Dirección', max_length=200, blank=True)
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='juntas')
    fecha_constitucion = models.DateField('Fecha de constitución', null=True, blank=True)
    activo = models.BooleanField('Activa', default=True)

    class Meta:
        ordering = ['-activo', 'nombre']
        constraints = [models.UniqueConstraint(fields=['territorio', 'nombre'], name='junta_nombre_territorio_unico')]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if self._state.adding:
            def guardar(**sobrescrituras):
                opciones = kwargs.copy()
                opciones.update(sobrescrituras)
                return super(JuntaVecinos, self).save(*args, **opciones)
            return guardar_con_codigo_automatico(self, 'JUN', guardar)
        original = type(self).objects.filter(pk=self.pk).values_list('codigo', flat=True).first()
        if original is not None:
            self.codigo = original
        return super().save(*args, **kwargs)


class ParticipacionJunta(models.Model):
    vecino = models.ForeignKey(Vecino, on_delete=models.PROTECT, related_name='participaciones')
    junta = models.ForeignKey(JuntaVecinos, on_delete=models.PROTECT, related_name='participaciones')
    dirigente = models.BooleanField('Es dirigente', default=False)
    cargo = models.CharField('Cargo', max_length=150, blank=True)
    fecha_incorporacion = models.DateField('Fecha de incorporación', null=True, blank=True)
    activo = models.BooleanField('Activa', default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['vecino', 'junta'], name='participacion_vecino_junta_unica')]

    def __str__(self):
        return f'{self.vecino} — {self.junta}'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.vecino_id and self.junta_id and self.vecino.territorio.delegacion_id != self.junta.territorio.delegacion_id:
            raise ValidationError('El vecino y la junta deben pertenecer a la misma delegación.')


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
        'evidencias': True,
        'agenda': True,
        'validar_evidencias': codigo in ('administrador', 'coordinador', 'verificador'),
        'catalogo_completo': catalogo and codigo in ('administrador', 'coordinador'),
    }


class Cargo(models.Model):
    nombre = models.CharField('Nombre', max_length=120, unique=True)
    descripcion = models.TextField('Descripción', blank=True)
    alcance = models.CharField('Alcance', max_length=20, choices=Rol.Alcance.choices, default=Rol.Alcance.GLOBAL)
    activo = models.BooleanField('Activo', default=True)

    class Meta:
        ordering = ['nombre']
        verbose_name_plural = 'Cargos'

    def __str__(self):
        return self.nombre


class Perfil(models.Model):
    """Extiende al usuario de Django con rol y delegaciones."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil',
        verbose_name='Usuario',
    )
    rut = models.CharField('RUT', max_length=20, unique=True, null=True, blank=True)
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
    def pendiente_activacion(self):
        return self.activo and not self.usuario.is_active and not self.usuario.has_usable_password()

    @property
    def estado_display(self):
        if self.pendiente_activacion:
            return 'Pendiente de activación'
        return 'Activo' if self.activo and self.usuario.is_active else 'Inactivo'

    @property
    def delegaciones_display(self):
        return ', '.join(self.delegaciones.values_list('nombre', flat=True))


class SolicitudTransferencia(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        APROBADA = 'aprobada', 'Aprobada'
        RECHAZADA = 'rechazada', 'Rechazada'

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='solicitudes_transferencia_recibidas',
        verbose_name='Usuario a transferir',
    )
    delegacion_origen = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='solicitudes_transferencia_origen',
        verbose_name='Delegación de origen',
    )
    delegacion_destino = models.ForeignKey(
        Delegacion,
        on_delete=models.PROTECT,
        related_name='solicitudes_transferencia_destino',
        verbose_name='Delegación de destino',
    )
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='solicitudes_transferencia_creadas',
        verbose_name='Solicitado por',
    )
    estado = models.CharField(
        'Estado',
        max_length=20,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    motivo = models.TextField('Motivo de la solicitud', blank=True)
    observacion_decision = models.TextField('Observación de la decisión', blank=True)
    decidido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='decisiones_transferencia',
        verbose_name='Decidido por',
    )
    creado = models.DateTimeField('Fecha de solicitud', auto_now_add=True)
    fecha_decision = models.DateTimeField('Fecha de decisión', null=True, blank=True)

    class Meta:
        verbose_name = 'Solicitud de transferencia'
        verbose_name_plural = 'Solicitudes de transferencia'
        ordering = ['-creado']
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delegacion_origen=models.F('delegacion_destino')),
                name='transferencia_delegaciones_distintas',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        estado='pendiente',
                        decidido_por__isnull=True,
                        fecha_decision__isnull=True,
                    )
                    | models.Q(
                        estado__in=('aprobada', 'rechazada'),
                        decidido_por__isnull=False,
                        fecha_decision__isnull=False,
                    )
                ),
                name='transferencia_decision_valida',
            ),
        ]

    def __str__(self):
        return (
            f'{self.usuario} · {self.delegacion_origen} → '
            f'{self.delegacion_destino} ({self.get_estado_display()})'
        )


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
