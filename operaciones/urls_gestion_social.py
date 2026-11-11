from django.urls import path

from operaciones import views

app_name = 'gestion_social'

urlpatterns = [
    path('', views.ListaGestionSocial.as_view(), name='lista'),
    path('nuevo/', views.CrearGestionSocial.as_view(), name='crear'),
    path('<int:pk>/', views.DetalleGestionSocial.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.EditarGestionSocial.as_view(), name='editar'),
    path('<int:pk>/desactivar/', views.DesactivarGestionSocial.as_view(), name='desactivar'),
]
