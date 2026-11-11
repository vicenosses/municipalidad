from django.urls import path

from operaciones import views

app_name = 'cartas'

urlpatterns = [
    path('', views.ListaCartas.as_view(), name='lista'),
    path('nuevo/', views.CrearCarta.as_view(), name='crear'),
    path('<int:pk>/', views.DetalleCarta.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.EditarCarta.as_view(), name='editar'),
    path('<int:pk>/desactivar/', views.DesactivarCarta.as_view(), name='desactivar'),
]
