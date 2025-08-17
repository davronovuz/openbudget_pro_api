from rest_framework import serializers
from django.utils import timezone
from .models import User, UserPhone, Transaction


class UserPhoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPhone
        fields = ("id", "phone_e164", "phone_snapshot", "created_at")
        read_only_fields = ("id", "phone_snapshot", "created_at")


class UserReadSerializer(serializers.ModelSerializer):
    phones = UserPhoneSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = (
            "user_id",
            "username",
            "full_name",
            "active",
            "language",
            "balance_sum",
            "created_at",
            "phones",
        )
        read_only_fields = ("created_at", "balance_sum")


class UserWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("user_id", "username", "full_name", "active", "language")

    def validate_language(self, value):
        field = self.Meta.model._meta.get_field("language")
        valid = {c for c, _ in field.choices} if field.choices else None
        if valid and value not in valid:
            raise serializers.ValidationError(f"language must be one of {sorted(valid)}")
        return value


class AddPhoneSerializer(serializers.Serializer):
    phone_e164 = serializers.CharField(max_length=24)

    def validate_phone_e164(self, v: str):
        v = v.strip()
        if not v.startswith("+") or len(v) < 7:
            raise serializers.ValidationError("phone_e164 must be E.164, e.g. +99890xxxxxxx")
        return v


class AdjustBalanceSerializer(serializers.Serializer):
    amount = serializers.IntegerField()
    type = serializers.ChoiceField(choices=[
        ("REWARD", "REWARD"), ("REFERRAL", "REFERRAL"),
        ("WITHDRAWAL", "WITHDRAWAL"), ("ADJUSTMENT", "ADJUSTMENT"), ("PENALTY", "PENALTY")
    ])
    reason = serializers.CharField(required=False, allow_blank=True)

    def validate_amount(self, v):
        if v == 0:
            raise serializers.ValidationError("amount must be non-zero")
        return v