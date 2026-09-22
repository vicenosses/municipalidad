from django.urls import path

from evidencias import views

app_name = 'evidencias'

urlpatterns = [
    path('', views.EvidenciaListView.as_view(), name='lista'),
    path('nueva/', views.EvidenciaCreateView.as_view(), name='crear'),
    path('<int:pk>/validar/', views.EvidenciaValidarView.as_view(), name='validar'),
]