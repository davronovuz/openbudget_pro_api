from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, required_channels, subscribe_status, snapshot_update, BalanceView, AddMoneyView, \
    DeductMoneyView, ReferralConfigView, ReferralGrantView, ReferralStatsView

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")

urlpatterns = [
    path("", include(router.urls)),
    path("api/required-channels/", required_channels),
    path("api/subscribe/status/", subscribe_status),
    path("api/subscriptions/snapshot/", snapshot_update),
    path("api/balance/<int:user_id>/", BalanceView.as_view(), name="balance"),
    path("api/balance/add/", AddMoneyView.as_view(), name="balance_add"),
    path("api/balance/deduct/", DeductMoneyView.as_view(), name="balance_deduct"),
    path("api/referral/config/", ReferralConfigView.as_view()),
    path("api/referral/grant/",  ReferralGrantView.as_view()),
    path("api/referral/stats/<int:user_id>/", ReferralStatsView.as_view()),
]



