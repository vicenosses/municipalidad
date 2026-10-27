from django.urls import path

from agenda.views import CompromisoDesdeActividadView
from atenciones import views

app_name = 'atenciones'

urlpatterns = [
    path('', views.AtencionListView.as_view(), name='lista'),
    path('nueva/', views.AtencionCreateView.as_view(), name='crear'),
    path(
        '<int:pk>/disponibilidad/',
        views.AtencionDisponibilidadView.as_view(),
        name='cambiar_disponibilidad',
    ),
    path(
        '<int:pk>/va-al-tubo/',
        views.AtencionVaAlTuboView.as_view(),
        name='cambiar_va_al_tubo',
    ),
    path('<int:pk>/estado/', views.AtencionEstadoView.as_view(), name='cambiar_estado'),
    path(
        '<int:actividad_pk>/agregar-a-agenda/',
        CompromisoDesdeActividadView.as_view(),
        name='agregar_a_agenda',
    ),
    path('<int:pk>/', views.AtencionDetailView.as_view(), name='detalle'),
]
