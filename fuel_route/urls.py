"""
URL configuration for fuel_route project.
"""
from django.contrib import admin
from django.urls import path, include

from route_planner.views import health, home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("", home, name="home"),
    path("api/", include("route_planner.urls")),
]