import requests
from django.conf import settings
from .models import Channel

BOT_TOKEN = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None


def _send(chat_id: int, text: str):
    if not BOT_API or not chat_id:
        return
    try:
        requests.post(
            f"{BOT_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception:
        pass


def notify_user(user_id: int, text: str):
    _send(user_id, text)


def notify_payout_channel(text: str):
    ch = Channel.objects.filter(type="PAYOUTS", is_active=True).order_by("-id").first()
    if ch:
        _send(ch.chat_id, text)

