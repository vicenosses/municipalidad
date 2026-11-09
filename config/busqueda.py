"""Búsquedas parciales sin distinguir mayúsculas en SQLite y MySQL/MariaDB."""
from django.db.models import Field
from django.db.models.lookups import IContains


def minusculas(valor):
    return valor.lower() if isinstance(valor, str) else valor


class ContieneSinMayusculas(IContains):
    lookup_name = 'icontains'

    def process_lhs(self, compiler, connection, lhs=None):
        sql, params = super().process_lhs(compiler, connection, lhs)
        if connection.vendor == 'sqlite':
            connection.ensure_connection()
            connection.connection.create_function('sgr_minusculas', 1, minusculas, deterministic=True)
            return f'sgr_minusculas({sql})', params
        if connection.vendor == 'mysql':
            return f'LOWER({sql})', params
        return sql, params

    def process_rhs(self, compiler, connection):
        sql, params = super().process_rhs(compiler, connection)
        if connection.vendor not in ('sqlite', 'mysql'):
            return sql, params
        if self.rhs_is_direct_value():
            return sql, [minusculas(p) for p in params]
        funcion = 'sgr_minusculas' if connection.vendor == 'sqlite' else 'LOWER'
        return f'{funcion}({sql})', params


def registrar_busqueda():
    Field.register_lookup(ContieneSinMayusculas)
