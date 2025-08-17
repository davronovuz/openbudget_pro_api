from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet,required_channels, subscribe_status, snapshot_update



router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    path("", include(router.urls)),
    path("api/required-channels/", required_channels),
    path("api/subscribe/status/", subscribe_status),
    path("api/subscriptions/snapshot/", snapshot_update),
]



