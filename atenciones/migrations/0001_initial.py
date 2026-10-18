import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('catalogos', '0001_initial'),
        ('usuarios', '0002_mantenedores'),
    ]

    operations = [
        migrations.CreateModel(
            name='AtencionCiudadana',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('solicitante', models.CharField(max_length=180, verbose_name='Solicitante')),
                ('descripcion', models.TextField(verbose_name='Descripción')),
                ('fecha_registro', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')),
                ('delegacion', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='atenciones',
                    to='usuarios.delegacion',
                    verbose_name='Delegación',
                )),
                ('responsable', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='atenciones_responsable',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Usuario responsable',
                )),
                ('subatencion', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='atenciones',
                    to='catalogos.subatencion',
                    verbose_name='Subatención',
                )),
                ('tipo', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='atenciones',
                    to='catalogos.tipoatencion',
                    verbose_name='Tipo de atención',
                )),
            ],
            options={
                'verbose_name': 'Atención ciudadana',
                'verbose_name_plural': 'Atenciones ciudadanas',
                'ordering': ['-fecha_registro'],
            },
        ),
    ]
