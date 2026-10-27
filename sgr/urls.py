from django.urls import path

from sgr import views, views_indicadores, views_aportes, views_informes

app_name = 'sgr'

urlpatterns = [
    path('informes/', views_informes.InformeSGRView.as_view(), name='informe'),
    path('aportes/indicadores-disponibles/', views_aportes.IndicadoresActividadView.as_view(), name='indicadores_actividad'),
    path('aportes/actividad/<int:actividad_pk>/', views_aportes.PropuestaAporteView.as_view(), name='aporte_proponer'),
    path('aportes/pendientes/', views_aportes.PendientesAporteView.as_view(), name='aportes_pendientes'),
    path('aportes/<int:pk>/validar/', views_aportes.ValidacionAporteView.as_view(), name='aporte_validar'),
    path('indicadores/', views_indicadores.IndicadorListView.as_view(), name='indicador_lista'),
    path('indicadores/nuevo/', views_indicadores.IndicadorCreateView.as_view(), name='indicador_crear'),
    path('indicadores/<int:pk>/', views_indicadores.IndicadorDetailView.as_view(), name='indicador_detalle'),
    path('indicadores/<int:pk>/editar/', views_indicadores.IndicadorUpdateView.as_view(), name='indicador_editar'),
    path('indicadores/<int:pk>/cambiar-estado/', views_indicadores.IndicadorEstadoView.as_view(), name='indicador_estado'),
    path('metas/<int:meta_pk>/indicadores/nuevo/', views_indicadores.IndicadorCreateView.as_view(),
         name='indicador_desde_meta'),
    path('metas/', views.MetaListView.as_view(), name='meta_lista'),
    path('metas/nueva/', views.MetaCreateView.as_view(), name='meta_crear'),
    path('metas/<int:pk>/', views.MetaDetailView.as_view(), name='meta_detalle'),
    path('metas/<int:pk>/editar/', views.MetaUpdateView.as_view(), name='meta_editar'),
    path('metas/<int:pk>/cambiar-estado/', views.MetaEstadoView.as_view(), name='meta_estado'),
    path('periodos/<int:periodo_pk>/metas/nueva/', views.MetaCreateView.as_view(),
         name='meta_desde_periodo'),
    path('periodos/', views.PeriodoListView.as_view(), name='periodo_lista'),
    path('periodos/nuevo/', views.PeriodoCreateView.as_view(), name='periodo_crear'),
    path('periodos/<int:pk>/', views.PeriodoDetailView.as_view(), name='periodo_detalle'),
    path('periodos/<int:pk>/editar/', views.PeriodoUpdateView.as_view(), name='periodo_editar'),
    path('periodos/<int:pk>/cambiar-estado/', views.PeriodoEstadoView.as_view(), name='periodo_estado'),
]
