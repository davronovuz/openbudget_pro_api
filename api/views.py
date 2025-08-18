from django.db import transaction
from django.db.models import F, Sum
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.filters import SearchFilter

from .models import User, UserPhone, Transaction, Referral, Setting
from .serializers import (
    UserReadSerializer, UserWriteSerializer,
    UserPhoneSerializer, AddPhoneSerializer, AdjustBalanceSerializer,
    RequiredChannelSerializer, SubscriptionSnapshotSerializer, AddRequestSerializer, DeductRequestSerializer,
    BalanceResponseSerializer, ReferralConfigOut, ReferralGrantIn, ReferralStatsOut
)
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .subscribe import get_required_channels_cached, compute_subscribe_status, upsert_snapshot
from .models import RequiredChannel

from django.db import transaction as db_tx
from django.db.models import F
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, serializers

from .models import User, Transaction


BOT_SECRET = "super-strong-random-secret-key"









class UserPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 200


def _snapshot(phone_e164: str) -> str:
    # Juda sodda normalizatsiya: "+99890xxxxxxx" -> "99890xxxxxxx"
    return phone_e164.replace("+", "").replace(" ", "")


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("-created_at")
    lookup_field = "user_id"
    pagination_class = UserPagination
    filter_backends = [SearchFilter]
    search_fields = ["username", "full_name", "user_id"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return UserWriteSerializer
        return UserReadSerializer

    # --- List with smart filters: /api/v1/users?active=true&language=uz ---
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        active = request.query_params.get("active")
        lang = request.query_params.get("language")
        if active is not None:
            if active.lower() in ("1", "true", "yes"):
                qs = qs.filter(active=True)
            elif active.lower() in ("0", "false", "no"):
                qs = qs.filter(active=False)
        if lang:
            qs = qs.filter(language=lang)
        page = self.paginate_queryset(qs)
        ser = UserReadSerializer(page, many=True)
        return self.get_paginated_response(ser.data)

    # --- Idempotent upsert ---
    def create(self, request, *args, **kwargs):
        ser = UserWriteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        user, created = User.objects.update_or_create(
            user_id=data["user_id"],
            defaults={
                "username": data.get("username"),
                "full_name": data.get("full_name"),
                "language": data.get("language"),
                "active": data.get("active", True),
            },
        )
        out = UserReadSerializer(user)
        return Response({"ok": True, "created": created, "user": out.data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    # --- Block / Unblock ---
    @action(detail=True, methods=["patch"], url_path="block")
    def block(self, request, user_id=None):
        user = self.get_object()
        if not user.active:
            return Response({"ok": True, "already": True, "active": False})
        user.active = False
        user.save(update_fields=["active"])
        return Response({"ok": True, "active": False})

    @action(detail=True, methods=["patch"], url_path="unblock")
    def unblock(self, request, user_id=None):
        user = self.get_object()
        if user.active:
            return Response({"ok": True, "already": True, "active": True})
        user.active = True
        user.save(update_fields=["active"])
        return Response({"ok": True, "active": True})

    # --- Phone add/remove ---
    @action(detail=True, methods=["post"], url_path="phones")
    def add_phone(self, request, user_id=None):
        user = self.get_object()
        ser = AddPhoneSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        e164 = ser.validated_data["phone_e164"]
        snap = _snapshot(e164)
        obj, created = UserPhone.objects.get_or_create(
            user=user, phone_e164=e164,
            defaults={"phone_snapshot": snap}
        )
        # Agar mavjud bo'lsa, snapshotni tekshirib yangilash ham mumkin
        if not created and obj.phone_snapshot != snap:
            obj.phone_snapshot = snap
            obj.save(update_fields=["phone_snapshot"])
        return Response({"ok": True, "created": created, "phone": UserPhoneSerializer(obj).data},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["delete"], url_path="phones/(?P<phone_id>[^/.]+)")
    def remove_phone(self, request, user_id=None, phone_id=None):
        user = self.get_object()
        try:
            phone = user.phones.get(pk=phone_id)
        except UserPhone.DoesNotExist:
            return Response({"detail": "phone not found"}, status=404)
        phone.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --- Balance adjust (admin/internal) ---
    @action(detail=True, methods=["post"], url_path="adjust-balance")
    def adjust_balance(self, request, user_id=None):
        user = self.get_object()
        ser = AdjustBalanceSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        amount = ser.validated_data["amount"]
        ttype = ser.validated_data["type"]
        reason = ser.validated_data.get("reason", "")
        with transaction.atomic():
            Transaction.objects.create(
                user=user, type=ttype, amount_sum=amount, ref_id=None
            )
            User.objects.filter(pk=user.pk).update(balance_sum=F("balance_sum") + amount)
            user.refresh_from_db(fields=["balance_sum"])
        return Response({"ok": True, "new_balance": user.balance_sum})



@api_view(["GET"])  # Bot/Frontend required ro'yxatni oladi
@permission_classes([AllowAny])
def required_channels(request):
    data = get_required_channels_cached()
    return Response({"required": data})

@api_view(["GET"])  # Bot/Frontend yakuniy holatni oladi
@permission_classes([AllowAny])
def subscribe_status(request):
    try:
        user_id = int(request.query_params.get("user_id"))
    except Exception:
        return Response({"detail": "user_id required"}, status=status.HTTP_400_BAD_REQUEST)
    result = compute_subscribe_status(user_id)
    return Response(result)

@api_view(["POST"])  # Bot snapshot jo'natadi (getChatMember natijasi)
@permission_classes([AllowAny])
def snapshot_update(request):
    secret = request.headers.get("X-Bot-Secret") or request.data.get("bot_secret")
    if not BOT_SECRET or secret != BOT_SECRET:
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    try:
        user_id = int(request.data.get("user_id"))
        channel_id = int(request.data.get("channel_id"))  # RequiredChannel.id
        is_member = bool(request.data.get("is_member"))
        error = request.data.get("error")
    except Exception:
        return Response({"detail": "invalid payload"}, status=status.HTTP_400_BAD_REQUEST)

    # channel mavjudligini minimal tekshiruv (agar xohlasangiz)
    if not RequiredChannel.objects.filter(id=channel_id, is_active=True).exists():
        return Response({"detail": "channel not active"}, status=status.HTTP_400_BAD_REQUEST)

    upsert_snapshot(user_id, channel_id, is_member, error)
    return Response({"ok": True})




INCOME_TYPES = {"REWARD", "REFERRAL"}
OUTCOME_TYPES = {"WITHDRAWAL", "PENALTY"}
ADJUSTMENT = "ADJUSTMENT"


def _get_user_or_404(user_id: int) -> User:
    return get_object_or_404(User, pk=user_id)


# -------------------------
# Views
# -------------------------
class BalanceView(APIView):
    """GET /api/balance/<int:user_id>/ — current balance from User.balance_sum"""

    authentication_classes = []
    permission_classes = []  # make it IsAdminUser if needed

    def get(self, request, user_id: int):
        user = _get_user_or_404(user_id)
        data = BalanceResponseSerializer({"user_id": user.user_id, "balance_sum": user.balance_sum}).data
        return Response(data)


class AddMoneyView(APIView):
    """POST /api/balance/add/ — credit user & write Transaction
    Body: { user_id, amount_sum (>0), type: REWARD|REFERRAL|ADJUSTMENT, ref_id? }
    """

    # Example: restrict to admins only
    # permission_classes = [permissions.IsAdminUser]
    authentication_classes = []
    permission_classes = []

    @db_tx.atomic
    def post(self, request):
        ser = AddRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = _get_user_or_404(ser.validated_data["user_id"])
        amount = ser.validated_data["amount_sum"]  # positive int
        tx_type = ser.validated_data["type"]
        ref_id = ser.validated_data.get("ref_id")

        # Map ADJUSTMENT as income (positive) here; if you need negative, use Deduct API with ADJUSTMENT
        # Write transaction first for a complete audit trail
        Transaction.objects.create(
            user=user,
            type=tx_type,
            amount_sum=amount,  # positive
            ref_id=ref_id,
        )
        # Increment balance safely
        User.objects.filter(pk=user.user_id).update(balance_sum=F("balance_sum") + amount)
        user.refresh_from_db(fields=["balance_sum"])

        return Response({
            "ok": True,
            "user_id": user.user_id,
            "delta": amount,
            "type": tx_type,
            "balance_sum": user.balance_sum,
        }, status=status.HTTP_201_CREATED)



class DeductMoneyView(APIView):
    """POST /api/balance/deduct/ — debit user & write Transaction
    Body: { user_id, amount_sum (>0), type: WITHDRAWAL|PENALTY|ADJUSTMENT, ref_id? }
    Stores negative amount_sum in Transaction for outcomes.
    """

    # permission_classes = [permissions.IsAdminUser]
    authentication_classes = []
    permission_classes = []

    @db_tx.atomic
    def post(self, request):
        ser = DeductRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = _get_user_or_404(ser.validated_data["user_id"])
        amount = ser.validated_data["amount_sum"]  # positive int
        tx_type = ser.validated_data["type"]
        ref_id = ser.validated_data.get("ref_id")

        # Sufficient funds check
        if user.balance_sum < amount:
            return Response({"ok": False, "error": "INSUFFICIENT_BALANCE", "balance_sum": user.balance_sum}, status=400)

        # Write outcome as negative in transactions (your model comment matches this)
        Transaction.objects.create(
            user=user,
            type=tx_type,
            amount_sum= -amount,  # negative row for outcome
            ref_id=ref_id,
        )
        # Decrement balance safely
        User.objects.filter(pk=user.user_id).update(balance_sum=F("balance_sum") - amount)
        user.refresh_from_db(fields=["balance_sum"])

        return Response({
            "ok": True,
            "user_id": user.user_id,
            "delta": -amount,
            "type": tx_type,
            "balance_sum": user.balance_sum,
        }, status=status.HTTP_201_CREATED)



def get_global_settings():
    s, _ = Setting.objects.get_or_create(key="GLOBAL")
    if not hasattr(s, "referral_reward_sum"):
        s.referral_reward_sum = 2000
    if not hasattr(s, "bot_username"):
        s.bot_username = "openbudget_humo_bot"  # ✅ fixed to your bot
    return s


class ReferralConfigView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        s = get_global_settings()
        data = {"referral_reward_sum": s.referral_reward_sum, "bot_username": s.bot_username}
        return Response(ReferralConfigOut(data).data)

class ReferralGrantView(APIView):
    authentication_classes = []
    permission_classes = []

    @db_tx.atomic
    def post(self, request):
        ser = ReferralGrantIn(data=request.data)
        ser.is_valid(raise_exception=True)
        referrer = get_object_or_404(User, pk=ser.validated_data["referrer_user_id"])
        referred = get_object_or_404(User, pk=ser.validated_data["referred_user_id"])

        if referrer.user_id == referred.user_id:
            return Response({"ok": False, "error": "SELF_REFERRAL_FORBIDDEN"}, status=400)

        ref, _ = Referral.objects.get_or_create(
            referrer_user=referrer,
            referred_user=referred,
            defaults={"status": "PENDING", "bonus_sum": 0},
        )

        if ref.status == "PAID":
            return Response({"ok": True, "already_paid": True, "reward": ref.bonus_sum}, status=200)

        reward = get_global_settings().referral_reward_sum or 0
        if reward > 0:
            Transaction.objects.create(user=referrer, type="REFERRAL", amount_sum=reward, ref_id=ref.id)
            User.objects.filter(pk=referrer.user_id).update(balance_sum=F("balance_sum") + reward)
            referrer.refresh_from_db(fields=["balance_sum"])

        ref.status = "PAID" if reward > 0 else "QUALIFIED"
        ref.bonus_sum = reward
        ref.reason = "Auto grant on referral join"
        ref.save(update_fields=["status", "bonus_sum", "reason"])

        return Response({
            "ok": True,
            "paid": reward > 0,
            "reward": reward,
            "referrer_balance_sum": referrer.balance_sum if reward > 0 else None,
        }, status=201)

class ReferralStatsView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, user_id: int):
        get_object_or_404(User, pk=user_id)
        invited_count = Referral.objects.filter(referrer_user_id=user_id).count()
        paid_sum = Referral.objects.filter(referrer_user_id=user_id, status="PAID").aggregate(s=Sum("bonus_sum"))["s"] or 0
        return Response(ReferralStatsOut({"invited_count": invited_count, "paid_sum": paid_sum}).data)
