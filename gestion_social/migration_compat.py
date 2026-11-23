"""Compatibilidad entre las dos ramas que crearon seguimientos independientes."""
from types import SimpleNamespace

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

        # SQLite conserva el nombre del índice al renombrar la tabla antigua.
        # Ese nombre puede coincidir con el índice que CreateModel necesita para
        # la nueva tabla de seguimientos, aunque ahora pertenezca a AccionGestionSocial.
        if acciones in tablas:
            nombre_indice_nuevo = schema_editor._create_index_name(
                modelo._meta.db_table,
                ['gestion_id'],
            )
            with conexion.cursor() as cursor:
                restricciones = conexion.introspection.get_constraints(cursor, acciones)
            indice_en_conflicto = next((
                nombre for nombre, detalle in restricciones.items()
                if nombre == nombre_indice_nuevo
                and detalle.get('index')
                and not detalle.get('unique')
                and detalle.get('columns') == ['gestion_id']
            ), None)
            if indice_en_conflicto:
                tabla_legacy = SimpleNamespace(
                    _meta=SimpleNamespace(db_table=acciones),
                )
                schema_editor.execute(
                    schema_editor._delete_index_sql(tabla_legacy, indice_en_conflicto)
                )

                nombre_indice_acciones = schema_editor._create_index_name(
                    acciones,
                    ['gestion_id'],
                )
                q = schema_editor.quote_name
                sql_indice = schema_editor.sql_create_index % {
                    'name': q(nombre_indice_acciones),
                    'table': q(acciones),
                    'columns': q('gestion_id'),
                    'include': '',
                    'extra': '',
                    'condition': '',
                }
                schema_editor.execute(sql_indice)

        if modelo._meta.db_table not in tablas:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
