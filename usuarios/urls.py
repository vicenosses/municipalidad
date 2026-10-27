from django.urls import path

from usuarios import views

app_name = 'usuarios'

urlpatterns = [
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
    path('roles/nuevo/', views.RolCreateView.as_view(), name='rol_crear'),
    path('roles/<int:pk>/', views.RolDetailView.as_view(), name='rol_detalle'),
    path('roles/<int:pk>/editar/', views.RolUpdateView.as_view(), name='rol_editar'),
    path('roles/<int:pk>/desactivar/', views.RolDesactivarView.as_view(), name='rol_desactivar'),
]
