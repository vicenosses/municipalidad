from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from api.views import (
    AccesoTokenView,
    AmpliacionViewSet,
    AporteViewSet,
    AsignacionMetaViewSet,
    AtencionViewSet,
    AuditoriaViewSet,
    CartaViewSet,
    CargoViewSet,
    CompromisoViewSet,
    DashboardView,
    DelegacionViewSet,
    EvidenciaViewSet,
    GestionSocialViewSet,
    HitoViewSet,
    IndicadorViewSet,
    MetaViewSet,
    MiPerfilView,
    RecuperacionAPIView,
    PeriodoViewSet,
    RolViewSet,
    SalirTokenView,
    SubAtencionViewSet,
    TerritorioViewSet,
    TipoAtencionViewSet,
    TuboView,
    VecinoViewSet,
)

router = DefaultRouter()
router.register('delegaciones', DelegacionViewSet, basename='delegacion')
router.register('territorios', TerritorioViewSet, basename='territorio')
router.register('cargos', CargoViewSet, basename='cargo')
router.register('roles', RolViewSet, basename='rol')
router.register('tipos-atencion', TipoAtencionViewSet, basename='tipo-atencion')
router.register('subatenciones', SubAtencionViewSet, basename='subatencion')
router.register('vecinos', VecinoViewSet, basename='vecino')
router.register('periodos', PeriodoViewSet, basename='periodo')
router.register('metas', MetaViewSet, basename='meta')
router.register('asignaciones', AsignacionMetaViewSet, basename='asignacion')
router.register('indicadores', IndicadorViewSet, basename='indicador')
router.register('actividades', AtencionViewSet, basename='actividad')
router.register('compromisos', CompromisoViewSet, basename='compromiso')
router.register('ampliaciones', AmpliacionViewSet, basename='ampliacion')
router.register('evidencias', EvidenciaViewSet, basename='evidencia')
router.register('aportes', AporteViewSet, basename='aporte')
router.register('gestiones-sociales', GestionSocialViewSet, basename='gestion-social')
router.register('cartas', CartaViewSet, basename='carta')
router.register('hitos', HitoViewSet, basename='hito')
router.register('auditoria', AuditoriaViewSet, basename='auditoria')

urlpatterns = [
    path('auth/token/', AccesoTokenView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', SalirTokenView.as_view(), name='token_blacklist'),
    path('auth/recuperacion/', RecuperacionAPIView.as_view(), name='recuperacion_api'),
    path('yo/', MiPerfilView.as_view(), name='mi_perfil'),
    path('tubo/', TuboView.as_view(), name='tubo'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]
