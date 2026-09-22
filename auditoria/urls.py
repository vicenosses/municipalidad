from django.urls import path

from auditoria import views

app_name = 'auditoria'

urlpatterns = [
    path('', views.AuditoriaListView.as_view(), name='lista'),
]