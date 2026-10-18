import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def cargar_roles_y_campos(apps, schema_editor):
    Delegacion = apps.get_model('usuarios', 'Delegacion')
    Rol = apps.get_model('usuarios', 'Rol')
    Perfil = apps.get_model('usuarios', 'Perfil')

    definiciones = [
        ('administrador', 'Administrador', 'Acceso total a mantenedores y auditoría.', 'global'),
        ('coordinador', 'Coordinador', 'Coordina delegación, catálogos y validaciones.', 'delegacion'),
        ('funcionario', 'Funcionario', 'Registra actividades, evidencias y atenciones.', 'delegacion'),
        ('verificador', 'Verificador', 'Valida evidencias y consulta atenciones.', 'delegacion'),
        ('delegado', 'Delegado', 'Gestiona agenda y operación de la delegación.', 'delegacion'),
    ]
    permisos = {
        'administrador': {
            'usuarios': True, 'roles': True, 'delegaciones': True, 'catalogos': True,
            'atenciones': True, 'auditoria': True, 'validar_evidencias': True,
        },
        'coordinador': {
            'usuarios': False, 'roles': False, 'delegaciones': True, 'catalogos': True,
            'atenciones': True, 'auditoria': True, 'validar_evidencias': True,
        },
        'funcionario': {
            'usuarios': False, 'roles': False, 'delegaciones': False, 'catalogos': False,
            'atenciones': True, 'auditoria': False, 'validar_evidencias': False,
        },
        'verificador': {
            'usuarios': False, 'roles': False, 'delegaciones': False, 'catalogos': False,
            'atenciones': True, 'auditoria': False, 'validar_evidencias': True,
        },
        'delegado': {
            'usuarios': False, 'roles': False, 'delegaciones': False, 'catalogos': False,
            'atenciones': True, 'auditoria': False, 'validar_evidencias': False,
        },
    }
    roles = {}
    for codigo, nombre, descripcion, alcance in definiciones:
        rol, _ = Rol.objects.get_or_create(
            codigo=codigo,
            defaults={
                'nombre': nombre,
                'descripcion': descripcion,
                'alcance': alcance,
                'permisos': permisos[codigo],
                'activo': True,
            },
        )
        roles[codigo] = rol

    for delegacion in Delegacion.objects.all():
        if not delegacion.codigo:
            delegacion.codigo = f'DEL-{delegacion.pk:03d}'
            delegacion.save(update_fields=['codigo'])

    funcionario = roles['funcionario']
    for perfil in Perfil.objects.all():
        codigo = perfil.rol or 'funcionario'
        perfil.rol_nuevo = roles.get(codigo, funcionario)
        perfil.save(update_fields=['rol_nuevo'])
        if perfil.delegacion_id:
            perfil.delegaciones.add(perfil.delegacion_id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('usuarios', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Rol',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30, unique=True, verbose_name='Código')),
                ('nombre', models.CharField(max_length=80, unique=True, verbose_name='Nombre')),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('permisos', models.JSONField(blank=True, default=dict, verbose_name='Permisos')),
                ('alcance', models.CharField(
                    choices=[('global', 'Global'), ('delegacion', 'Delegación')],
                    default='delegacion',
                    max_length=20,
                    verbose_name='Alcance',
                )),
                ('activo', models.BooleanField(default=True, verbose_name='Estado activo')),
            ],
            options={
                'verbose_name': 'Rol',
                'verbose_name_plural': 'Roles',
                'ordering': ['nombre'],
            },
        ),
        migrations.CreateModel(
            name='CodigoRecuperacion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo_hash', models.CharField(max_length=128)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('expira', models.DateTimeField()),
                ('intentos', models.PositiveSmallIntegerField(default=0)),
                ('usado', models.BooleanField(default=False)),
                ('usuario', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='codigos_recuperacion',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-creado']},
        ),
        migrations.AddField(
            model_name='delegacion',
            name='codigo',
            field=models.CharField(blank=True, default='', max_length=30, verbose_name='Código'),
        ),
        migrations.AddField(
            model_name='delegacion',
            name='direccion',
            field=models.CharField(blank=True, max_length=200, verbose_name='Dirección'),
        ),
        migrations.AddField(
            model_name='delegacion',
            name='comuna',
            field=models.CharField(blank=True, max_length=80, verbose_name='Comuna'),
        ),
        migrations.AddField(
            model_name='perfil',
            name='rol_nuevo',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='perfiles',
                to='usuarios.rol',
                verbose_name='Rol',
            ),
        ),
        migrations.AddField(
            model_name='perfil',
            name='delegaciones',
            field=models.ManyToManyField(
                blank=True,
                related_name='perfiles_autorizados',
                to='usuarios.delegacion',
                verbose_name='Delegaciones autorizadas',
            ),
        ),
        migrations.RunPython(cargar_roles_y_campos, noop),
        migrations.RemoveField(model_name='perfil', name='rol'),
        migrations.RenameField(model_name='perfil', old_name='rol_nuevo', new_name='rol'),
        migrations.AlterField(
            model_name='delegacion',
            name='codigo',
            field=models.CharField(max_length=30, unique=True, verbose_name='Código'),
        ),
        migrations.AlterField(
            model_name='delegacion',
            name='activa',
            field=models.BooleanField(default=True, verbose_name='Estado activo'),
        ),
    ]
