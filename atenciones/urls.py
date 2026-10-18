from django.urls import path

from atenciones import views

app_name = 'atenciones'

urlpatterns = [
    path('', views.AtencionListView.as_view(), name='lista'),
    path('nueva/', views.AtencionCreateView.as_view(), name='crear'),
    path('<int:pk>/', views.AtencionDetailView.as_view(), name='detalle'),
]
