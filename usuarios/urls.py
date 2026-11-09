from django.urls import path

from usuarios import views
from usuarios.territorios import TerritoriosView, TerritorioGuardarView
from usuarios.comunidad import ComunidadView, ComunidadGuardarView, ComunidadDetalleView, ComunidadEstadoView

app_name = 'usuarios'

urlpatterns = [
    path('<int:pk>/reenviar-activacion/', views.ReenviarActivacionView.as_view(), name='reenviar_activacion'),
    path('comunidad/<str:tipo>/', ComunidadView.as_view(), name='comunidad_lista'),
    path('comunidad/<str:tipo>/nuevo/', ComunidadGuardarView.as_view(), name='comunidad_crear'),
    path('comunidad/<str:tipo>/<int:pk>/editar/', ComunidadGuardarView.as_view(), name='comunidad_editar'),
    path('comunidad/<str:tipo>/<int:pk>/', ComunidadDetalleView.as_view(), name='comunidad_detalle'),
    path('comunidad/<str:tipo>/<int:pk>/estado/', ComunidadEstadoView.as_view(), name='comunidad_estado'),
    path('territorios/', TerritoriosView.as_view(), name='territorio_lista'),
    path('territorios/nuevo/', TerritorioGuardarView.as_view(), name='territorio_crear'),
    path('territorios/<int:pk>/editar/', TerritorioGuardarView.as_view(), name='territorio_editar'),
    path('', views.UsuarioListView.as_view(), name='lista'),
    path('nuevo/', views.UsuarioCreateView.as_view(), name='crear'),
    path('<int:pk>/', views.UsuarioDetailView.as_view(), name='detalle'),
    path('<int:pk>/editar/', views.UsuarioUpdateView.as_view(), name='editar'),
    path('<int:pk>/desactivar/', views.UsuarioDesactivarView.as_view(), name='desactivar'),
    path('transferencias/', views.TransferenciasView.as_view(), name='transferencias'),
    path(
        'transferencias/solicitar/',
        views.SolicitudTransferenciaCreateView.as_view(),
        name='transferencia_solicitar',
    ),
    path(
        'transferencias/usuarios/<int:pk>/',
        views.TransferenciaDirectaView.as_view(),
        name='transferencia_directa',
    ),
    path(
        'transferencias/solicitudes/<int:pk>/decidir/',
        views.TransferenciaDecisionView.as_view(),
        name='transferencia_decidir',
    ),
    path('sesion/delegacion/', views.DelegacionActivaView.as_view(), name='delegacion_activa'),
    path('delegaciones/', views.DelegacionListView.as_view(), name='delegacion_lista'),
    path('delegaciones/nueva/', views.DelegacionCreateView.as_view(), name='delegacion_crear'),
    path('delegaciones/<int:pk>/', views.DelegacionDetailView.as_view(), name='delegacion_detalle'),
    path('delegaciones/<int:pk>/editar/', views.DelegacionUpdateView.as_view(), name='delegacion_editar'),
    path('delegaciones/<int:pk>/desactivar/', views.DelegacionDesactivarView.as_view(), name='delegacion_desactivar'),
    path('roles/', views.RolListView.as_view(), name='rol_lista'),
    path('cargos/', views.CargoListView.as_view(), name='cargo_lista'),
    path('cargos/nuevo/', views.CargoCreateView.as_view(), name='cargo_crear'),
    path('cargos/<int:pk>/', views.CargoDetailView.as_view(), name='cargo_detalle'),
    path('cargos/<int:pk>/editar/', views.CargoUpdateView.as_view(), name='cargo_editar'),
    path('cargos/<int:pk>/estado/', views.CargoEstadoView.as_view(), name='cargo_estado'),
    path('roles/nuevo/', views.RolCreateView.as_view(), name='rol_crear'),
    path('roles/<int:pk>/', views.RolDetailView.as_view(), name='rol_detalle'),
    path('roles/<int:pk>/editar/', views.RolUpdateView.as_view(), name='rol_editar'),
    path('roles/<int:pk>/desactivar/', views.RolDesactivarView.as_view(), name='rol_desactivar'),
]
