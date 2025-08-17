from django.db import transaction
from django.db.models import F
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.filters import SearchFilter

from .models import User, UserPhone, Transaction
from .serializers import (
    UserReadSerializer, UserWriteSerializer,
    UserPhoneSerializer, AddPhoneSerializer, AdjustBalanceSerializer,
)


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


from django.shortcuts import render

# Create your views here.
