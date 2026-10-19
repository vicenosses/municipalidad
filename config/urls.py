from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from config.views import HomeView
from evidencias.views import EvidenciaArchivoView
from usuarios.auth_views import (
    LoginSGRView,
    RecuperacionCodigoView,
    RecuperacionNuevaView,
    RecuperacionSolicitarView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', LoginSGRView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('recuperacion/', RecuperacionSolicitarView.as_view(), name='recuperacion_solicitar'),
    path('recuperacion/codigo/', RecuperacionCodigoView.as_view(), name='recuperacion_codigo'),
    path('recuperacion/nueva/', RecuperacionNuevaView.as_view(), name='recuperacion_nueva'),
    path('', HomeView.as_view(), name='home'),
    path('usuarios/', include('usuarios.urls')),
    path('actividades/', include('actividades.urls')),
    path('evidencias/', include('evidencias.urls')),
    path('agenda/', include('agenda.urls')),
    path('auditoria/', include('auditoria.urls')),
    path(
        f'{settings.MEDIA_URL.lstrip("/").rstrip("/")}/evidencias/<int:pk>/',
        EvidenciaArchivoView.as_view(),
        name='evidencia_archivo',
    ),
    path('catalogos/', include('catalogos.urls')),
    path('atenciones/', include('atenciones.urls')),
]

handler403 = 'django.views.defaults.permission_denied'
