from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from config.views import HomeView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', HomeView.as_view(), name='home'),
    path('usuarios/', include('usuarios.urls')),
    path('actividades/', include('actividades.urls')),
    path('evidencias/', include('evidencias.urls')),
    path('agenda/', include('agenda.urls')),
    path('auditoria/', include('auditoria.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
