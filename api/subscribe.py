from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import RequiredChannel,SubscriptionSnapshot

CACHE_TTL = getattr(settings, "SUBSCRIBE_CACHE_TTL", 30)
ENFORCEMENT_MODE = getattr(settings, "SUBSCRIBE_ENFORCEMENT_MODE", "BLOCK")  # BLOCK | BONUS_ONLY


def get_required_channels_cached():
    key = "required_channels:v1"
    data = cache.get(key)
    if data is None:
        qs = RequiredChannel.objects.filter(is_active=True).order_by("priority", "id")
        data = list(qs.values("id", "title", "chat_id", "invite_link"))
        cache.set(key, data, CACHE_TTL)
    return data


def compute_subscribe_status(user_id: int) -> dict:
    """Backend hisobicha yakuniy holat.
    fully_subscribed: barcha active required kanallar bo'yicha MEMBER bo'lsa True.
    Agar snapshot yo'q bo'lsa, konservativ tarzda NOT_MEMBER deb hisoblaymiz.
    """
    required = get_required_channels_cached()
    if not required:
        return {"fully_subscribed": True, "enforcement_mode": ENFORCEMENT_MODE, "required": []}

    # snapshotlarni tortib kelamiz
    chan_ids = [rc["id"] for rc in required]
    snaps = SubscriptionSnapshot.objects.filter(user_id=user_id, channel_id__in=chan_ids)
    snap_map = {s.channel_id: s.status for s in snaps}

    # Mavjud bo'lmagan snapshotni NOT_MEMBER deb olamiz
    for rc in required:
        st = snap_map.get(rc["id"])
        if st != "MEMBER":
            return {"fully_subscribed": False, "enforcement_mode": ENFORCEMENT_MODE, "required": required}

    return {"fully_subscribed": True, "enforcement_mode": ENFORCEMENT_MODE, "required": required}


def upsert_snapshot(user_id: int, channel_id: int, is_member: bool, error: str | None = None):
    obj, _ = SubscriptionSnapshot.objects.get_or_create(user_id=user_id, channel_id=channel_id,
                                                        defaults={"status": "MEMBER" if is_member else "NOT_MEMBER"})
    obj.status = "MEMBER" if is_member else "NOT_MEMBER"
    obj.error = error
    obj.updated_at = timezone.now()
    obj.save(update_fields=["status", "error", "updated_at"])