from django.urls import path

from operaciones import views

app_name = 'reconocimientos'

urlpatterns = [
    path('', views.ListaReconocimientos.as_view(), name='lista'),
    path('nuevo/', views.CrearReconocimiento.as_view(), name='crear'),
    path('<int:pk>/editar/', views.EditarReconocimiento.as_view(), name='editar'),
]
