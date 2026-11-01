"""Configuración separada para ejecutar el proyecto en un servidor AWS."""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.getenv('DJANGO_ALLOWED_HOSTS', '').split(',') if host.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured('Configure DJANGO_ALLOWED_HOSTS para el servidor AWS.')

CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if origin.strip()]
STATIC_ROOT = BASE_DIR / 'staticfiles'  # noqa: F405

# Por defecto se requiere HTTPS. Para una prueba temporal sin TLS debe indicarse
# explícitamente DJANGO_HTTPS=false y no utilizar cuentas ni datos reales.
_https = os.getenv('DJANGO_HTTPS', 'true').lower() == 'true'
SECURE_SSL_REDIRECT = _https
SESSION_COOKIE_SECURE = _https
CSRF_COOKIE_SECURE = _https
if _https and os.getenv('DJANGO_TRUST_PROXY', 'false').lower() == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
