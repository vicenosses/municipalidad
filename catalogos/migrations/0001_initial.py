import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='ItemMeta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30, unique=True, verbose_name='Código')),
                ('nombre', models.CharField(max_length=150, verbose_name='Nombre')),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('activo', models.BooleanField(default=True, verbose_name='Estado activo')),
            ],
            options={
                'verbose_name': 'Ítem / meta',
                'verbose_name_plural': 'Ítems y metas',
                'ordering': ['codigo'],
            },
        ),
        migrations.CreateModel(
            name='TipoAtencion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30, unique=True, verbose_name='Código')),
                ('nombre', models.CharField(max_length=150, verbose_name='Nombre')),
                ('descripcion', models.TextField(blank=True, verbose_name='Descripción')),
                ('activo', models.BooleanField(default=True, verbose_name='Estado activo')),
            ],
            options={
                'verbose_name': 'Tipo de atención',
                'verbose_name_plural': 'Tipos de atención',
                'ordering': ['codigo'],
            },
        ),
        migrations.CreateModel(
            name='SubAtencion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30, unique=True, verbose_name='Código')),
                ('nombre', models.CharField(max_length=150, verbose_name='Nombre')),
                ('activo', models.BooleanField(default=True, verbose_name='Estado activo')),
                ('tipo', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='subatenciones',
                    to='catalogos.tipoatencion',
                    verbose_name='Tipo de atención',
                )),
            ],
            options={
                'verbose_name': 'Subatención',
                'verbose_name_plural': 'Subatenciones',
                'ordering': ['codigo'],
            },
        ),
    ]
