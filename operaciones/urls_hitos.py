from django.urls import path

from operaciones import views

app_name = 'hitos'

urlpatterns = [
    path('', views.ListaHitos.as_view(), name='lista'),
    path('nuevo/', views.CrearHito.as_view(), name='crear'),
    path('<int:pk>/', views.DetalleHito.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.EditarHito.as_view(), name='editar'),
    path('<int:pk>/desactivar/', views.DesactivarHito.as_view(), name='desactivar'),
]
