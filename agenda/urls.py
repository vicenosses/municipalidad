from django.urls import include, path

from agenda import views
from agenda.tubo import TuboGestionView

app_name = 'agenda'

urlpatterns = [
    path('cartas/', include(('operaciones.urls_cartas', 'cartas'), namespace='cartas')),
    path('hitos/', include(('operaciones.urls_hitos', 'hitos'), namespace='hitos')),
    path('', views.CompromisoListView.as_view(), name='lista'),
    path('tubo/', TuboGestionView.as_view(), name='tubo'),
    path('nuevo/', views.CompromisoCreateView.as_view(), name='crear'),
    path('ampliaciones/', views.AmpliacionesListView.as_view(), name='ampliaciones'),
    path('ampliaciones/<int:pk>/decidir/', views.DecidirAmpliacionView.as_view(), name='decidir_ampliacion'),
    path('<int:pk>/seguimiento/', views.AgregarSeguimientoCompromisoView.as_view(), name='agregar_seguimiento'),
    path('<int:pk>/solicitar-ampliacion/', views.SolicitarAmpliacionView.as_view(), name='solicitar_ampliacion'),
    path('<int:pk>/', views.CompromisoDetailView.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.CompromisoUpdateView.as_view(), name='editar'),
]
