from django.urls import path

from catalogos import views

app_name = 'catalogos'

urlpatterns = [
    path('items/', views.ItemListView.as_view(), name='item_lista'),
    path('items/nuevo/', views.ItemCreateView.as_view(), name='item_crear'),
    path('items/<int:pk>/', views.ItemDetailView.as_view(), name='item_detalle'),
    path('items/<int:pk>/editar/', views.ItemUpdateView.as_view(), name='item_editar'),
    path('items/<int:pk>/desactivar/', views.ItemDesactivarView.as_view(), name='item_desactivar'),
    path('tipos/', views.TipoListView.as_view(), name='tipo_lista'),
    path('tipos/nuevo/', views.TipoCreateView.as_view(), name='tipo_crear'),
    path('tipos/<int:pk>/', views.TipoDetailView.as_view(), name='tipo_detalle'),
    path('tipos/<int:pk>/editar/', views.TipoUpdateView.as_view(), name='tipo_editar'),
    path('tipos/<int:pk>/desactivar/', views.TipoDesactivarView.as_view(), name='tipo_desactivar'),
    path('subatenciones/', views.SubListView.as_view(), name='sub_lista'),
    path('subatenciones/nueva/', views.SubCreateView.as_view(), name='sub_crear'),
    path('subatenciones/<int:pk>/', views.SubDetailView.as_view(), name='sub_detalle'),
    path('subatenciones/<int:pk>/editar/', views.SubUpdateView.as_view(), name='sub_editar'),
    path('subatenciones/<int:pk>/desactivar/', views.SubDesactivarView.as_view(), name='sub_desactivar'),
]
