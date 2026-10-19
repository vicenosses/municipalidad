import uuid

import django.db.models.deletion
import evidencias.models
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
from django.utils.text import slugify


def completar_metadatos(apps, schema_editor):
    Evidencia = apps.get_model('evidencias', 'Evidencia')
    alias = schema_editor.connection.alias
    for evidencia in Evidencia.objects.using(alias).select_related('subido_por').iterator():
        extension = evidencia.archivo.name.rsplit('.', 1)[-1].lower()
        tipo = 'video' if extension in {'mp4', 'webm'} else 'imagen'
        usuario = slugify(evidencia.subido_por.username)[:32]
        if not usuario:
            usuario = f'usuario-{evidencia.subido_por_id}'
        fecha = timezone.localtime(evidencia.fecha_subida).strftime('%Y%m%d')
        evidencia.identificador = f'{fecha}_{usuario}_{tipo}_{uuid.uuid4().hex}'
        evidencia.tipo_archivo = tipo
        evidencia.save(update_fields=['identificador', 'tipo_archivo'], using=alias)


class Migration(migrations.Migration):

    dependencies = [
        ('actividades', '0001_initial'),
        ('atenciones', '0001_initial'),
        ('evidencias', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='evidencia',
            name='actividad',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='evidencias',
                to='actividades.actividad',
                verbose_name='Actividad',
            ),
        ),
        migrations.AddField(
            model_name='evidencia',
            name='atencion',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='evidencias',
                to='atenciones.atencionciudadana',
                verbose_name='Atención ciudadana',
            ),
        ),
        migrations.AddField(
            model_name='evidencia',
            name='identificador',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=160,
                null=True,
                verbose_name='Identificador',
            ),
        ),
        migrations.AddField(
            model_name='evidencia',
            name='tipo_archivo',
            field=models.CharField(
                choices=[('imagen', 'Imagen'), ('video', 'Video')],
                default='imagen',
                max_length=10,
                verbose_name='Tipo de archivo',
            ),
        ),
        migrations.AlterField(
            model_name='evidencia',
            name='archivo',
            field=models.FileField(
                upload_to=evidencias.models.ruta_evidencia,
                verbose_name='Archivo',
            ),
        ),
        migrations.RunPython(completar_metadatos, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='evidencia',
            name='identificador',
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=160,
                unique=True,
                verbose_name='Identificador',
            ),
        ),
        migrations.AddConstraint(
            model_name='evidencia',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(actividad__isnull=False, atencion__isnull=True)
                    | models.Q(actividad__isnull=True, atencion__isnull=False)
                ),
                name='evidencia_actividad_o_atencion',
            ),
        ),
    ]
