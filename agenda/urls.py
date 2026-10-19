from django.urls import path

from agenda import views

app_name = 'agenda'

urlpatterns = [
    path('', views.CompromisoListView.as_view(), name='lista'),
    path('nuevo/', views.CompromisoCreateView.as_view(), name='crear'),
    path('<int:pk>/', views.CompromisoDetailView.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.CompromisoUpdateView.as_view(), name='editar'),
]