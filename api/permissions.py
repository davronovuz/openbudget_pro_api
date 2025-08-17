from rest_framework.permissions import BasePermission
from .subscribe import compute_subscribe_status

class IsSubscribedOr403(BasePermission):
    message = "Majburiy kanallarga obuna bo'ling (then /check)."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        # Agar user modelda telegram_id bo'lsa undan olamiz, aks holda pk dan
        tg_id = getattr(user, "user_id", None) or user.pk

        result = compute_subscribe_status(tg_id)
        return bool(result.get("fully_subscribed"))
