from django.urls import path
from .views import RouteOptimizerView

urlpatterns = [
    path('route/optimize/', RouteOptimizerView.as_view(), name='route-optimize'),
]