"""Etiquetas de interfaz; los códigos persistidos permanecen intactos."""
ACCIONES = {
    'asociar_indicador': 'Indicador asociado',
    'cambiar_indicador': 'Propuesta de aporte modificada',
    'corregir_aporte': 'Aporte corregido',
    'enviar_aporte': 'Aporte enviado',
    'reenviar_aporte': 'Aporte reenviado',
    'validar_aporte': 'Aporte: cumple',
    'requerir_correccion_aporte': 'Aporte: requiere corrección',
    'no_cumple_aporte': 'Aporte: no cumple',
    'reiniciar_aporte_reapertura': 'Validación reiniciada por reapertura',
    'cambiar_objetivo_indicador': 'Objetivo del Indicador modificado',
    'cambiar_ponderacion_indicador': 'Ponderación del Indicador modificada',
    'crear_indicador': 'Indicador creado',
    'editar_indicador': 'Indicador editado',
    'activar_indicador': 'Indicador activado',
    'desactivar_indicador': 'Indicador desactivado',
    'crear_meta': 'Meta creada',
    'editar_meta': 'Meta editada',
    'activar_meta': 'Meta activada',
    'desactivar_meta': 'Meta desactivada',
    'crear_periodo': 'Período creado',
    'editar_periodo': 'Período editado',
    'activar_periodo': 'Período activado',
    'desactivar_periodo': 'Período desactivado',
    'crear': 'Creación',
    'editar': 'Edición',
    'cambiar_estado': 'Cambio de estado',
    'cambiar_va_al_tubo': 'Va al tubo',
    'crear_compromiso_desde_actividad': 'Agenda',
    'habilitar': 'Actividad habilitada',
    'deshabilitar': 'Actividad deshabilitada',
    'validar': 'Validación de evidencia',
    'agregar': 'Evidencia agregada',
}

MODULOS = {
    'sgr': ('SGR', ('sgr.Periodo', 'sgr.Meta', 'sgr.Indicador', 'sgr.AporteIndicador')),
    'actividades': ('Actividades', ('atenciones.AtencionCiudadana',)),
    'agenda': ('Agenda', ('agenda.Compromiso',)),
    'evidencias': ('Evidencias', ('evidencias.Evidencia',)),
    'catalogos': ('Catálogos', (
        'catalogos.ItemMeta', 'catalogos.TipoAtencion', 'catalogos.SubAtencion',
        'catalogos.SolicitudCatalogoGeneral',
    )),
    'usuarios': ('Usuarios', ('auth.User', 'usuarios.Perfil', 'usuarios.Rol', 'usuarios.Delegacion')),
    'transferencias': ('Transferencias', ('usuarios.SolicitudTransferencia',)),
}


def etiqueta_accion(accion):
    return ACCIONES.get(accion, accion.replace('_', ' ').capitalize())


def presentar_registros(registros):
    for registro in registros:
        registro.accion_legible = etiqueta_accion(registro.accion)
        registro.modulo_legible = next(
            (nombre for nombre, modelos in MODULOS.values() if registro.modelo in modelos),
            registro.modelo,
        )
    return registros
