"""Compatibilidad entre las dos ramas que crearon seguimientos independientes."""
from django.db import migrations


class CrearSeguimientoCompatible(migrations.CreateModel):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        conexion = schema_editor.connection
        tablas = set(conexion.introspection.table_names())
        original = 'gestion_social_seguimientogestionsocial'
        acciones = 'gestion_social_acciongestionsocial'
        if original in tablas:
            with conexion.cursor() as cursor:
                columnas = {col.name for col in conexion.introspection.get_table_description(cursor, original)}
            if 'area_institucion' in columnas and 'descripcion' not in columnas:
                if acciones in tablas:
                    raise RuntimeError('No es posible reconciliar dos tablas de acciones sociales automáticamente.')
                q = schema_editor.quote_name
                schema_editor.execute(f'ALTER TABLE {q(original)} RENAME TO {q(acciones)}')
                tablas.remove(original)
                tablas.add(acciones)
        modelo = to_state.apps.get_model(app_label, self.name)
        if modelo._meta.db_table not in tablas:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
