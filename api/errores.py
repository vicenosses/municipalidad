"""Errores generales sin detalles internos para consumidores de la API."""
from django.http import JsonResponse
from django.views.defaults import page_not_found, server_error


def no_encontrado(request, exception):
    if request.path_info.startswith('/api/'):
        return JsonResponse({'detail': 'Recurso no encontrado.'}, status=404)
    return page_not_found(request, exception)


def error_interno(request):
    if request.path_info.startswith('/api/'):
        return JsonResponse({'detail': 'No fue posible completar la solicitud.'}, status=500)
    return server_error(request)
