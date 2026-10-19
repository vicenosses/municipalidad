from django.urls import path

from evidencias import views

app_name = 'evidencias'

urlpatterns = [
    path('', views.EvidenciaListView.as_view(), name='lista'),
    path('<int:pk>/', views.EvidenciaDetailView.as_view(), name='detalle'),
    path('nueva/', views.EvidenciaCreateView.as_view(), name='crear'),
    path('atencion/<int:pk>/nueva/', views.EvidenciaAtencionCreateView.as_view(), name='atencion_crear'),
    path('agenda/<int:pk>/nueva/', views.EvidenciaCompromisoCreateView.as_view(), name='agenda_crear'),
    path('<int:pk>/validar/', views.EvidenciaValidarView.as_view(), name='validar'),
]