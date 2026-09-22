from django.urls import path

from usuarios import views

app_name = 'usuarios'

urlpatterns = [
    path('', views.UsuarioListView.as_view(), name='lista'),
    path('nuevo/', views.UsuarioCreateView.as_view(), name='crear'),
    path('<int:pk>/editar/', views.PerfilUpdateView.as_view(), name='editar'),
    path('delegaciones/nueva/', views.DelegacionCreateView.as_view(), name='delegacion_crear'),
]