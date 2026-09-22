from django.urls import path

from actividades import views

app_name = 'actividades'

urlpatterns = [
    path('', views.ActividadListView.as_view(), name='lista'),
    path('nueva/', views.ActividadCreateView.as_view(), name='crear'),
]