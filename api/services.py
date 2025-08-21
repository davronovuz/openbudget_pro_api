# finance/services.py
from django.db import transaction as dbtx
from django.core.exceptions import ValidationError

from .masking import mask_destination
from .models import Withdrawal, Transaction, User  # sizning joylashuvingizga mos import qiling

MIN_WITHDRAW = 20000  # faqat minimal qoida (modelga tegmadik)

@dbtx.atomic
def create_withdrawal(*, user: User, method: str, destination_raw: str, amount: int) -> Withdrawal:
    """
    1) Minimal summa tekshiruvi
    2) Ochiq PENDING bor-yo'qligi
    3) User balansini select_for_update bilan qulflash va yetarliligini tekshirish
    4) Withdrawal (PENDING) yozish (destination_masked bilan)
    5) Transaction (WITHDRAWAL, manfiy) yozish
    6) User.balance_sum ni kamaytirish
    """
    if amount < MIN_WITHDRAW:
        raise ValidationError(f"Minimal yechish {MIN_WITHDRAW} so'm.")


    if Withdrawal.objects.filter(user=user, status__in=["PENDING", "APPROVED"]).exists():
        raise ValidationError("❗ Sizda hali tugallanmagan pul  yechish so‘rovi bor. Iltimos yakunlashni kuting.")

    # Balansni qulflash
    u = User.objects.select_for_update().get(pk=user.pk)
    if u.balance_sum < amount:
        raise ValidationError("Balans yetarli emas.")

    # Masklab saqlaymiz (modelni o'zgartirmaymiz)
    dest_mask = mask_destination(method, destination_raw)

    # Withdrawal yozish (faqat mask)
    w = Withdrawal.objects.create(
        user=u,
        amount_sum=amount,
        method=method,
        destination_masked=dest_mask,
        status="PENDING",
    )

    # Tranzaksiya: manfiy yozuv (hold sifatida)
    Transaction.objects.create(
        user=u,
        type="WITHDRAWAL",
        amount_sum=-amount,
        ref_id=w.id,
    )

    # Balansni tushirish
    u.balance_sum -= amount
    u.save(update_fields=["balance_sum"])

    return w


from django.db import transaction as dbtx
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import User, Transaction, Withdrawal, AdminLog


@dbtx.atomic
def approve_withdrawal(*, w: Withdrawal, admin_id: int, note: str = "") -> Withdrawal:
    """
    PENDING → APPROVED
    - Status tekshiruv
    - AdminLog yozish
    - (Balansga tegmaydi — balans yaratilganda allaqachon yechilgan)
    """
    if w.status != "PENDING":
        raise ValidationError("Faqat PENDING tasdiqlanadi.")

    w.status = "APPROVED"
    w.admin_id = admin_id
    if note:
        w.admin_note = ((w.admin_note or "") + f"\n[approve] {note}").strip()
    w.updated_at = timezone.now()
    w.save(update_fields=["status", "admin_id", "admin_note", "updated_at"])

    AdminLog.objects.create(
        admin_id=admin_id,
        action="WITHDRAW_APPROVE",
        payload_json={"withdrawal_id": w.id, "user_id": w.user_id, "amount_sum": w.amount_sum},
    )
    return w


@dbtx.atomic
def reject_withdrawal(*, w: Withdrawal, admin_id: int, reason: str = "") -> Withdrawal:
    """
    PENDING/APPROVED → REJECTED
    - User balansiga summa qaytariladi
    - Transaction(ADJUSTMENT, +amount) yoziladi
    - AdminLog yoziladi
    """
    if w.status not in ("PENDING", "APPROVED"):
        raise ValidationError("Faqat PENDING/APPROVED rad qilinadi.")

    # Balansni qaytarish (qattiq qulf bilan)
    u = User.objects.select_for_update().get(pk=w.user_id)
    u.balance_sum += w.amount_sum
    u.save(update_fields=["balance_sum"])

    # Qaytarish tranzaksiyasi
    Transaction.objects.create(
        user=u,
        type="ADJUSTMENT",
        amount_sum=w.amount_sum,   # qaytarish +X
        ref_id=w.id,
    )

    w.status = "REJECTED"
    w.admin_id = admin_id
    if reason:
        w.admin_note = ((w.admin_note or "") + f"\n[reject] {reason}").strip()
    w.updated_at = timezone.now()
    w.save(update_fields=["status", "admin_id", "admin_note", "updated_at"])

    AdminLog.objects.create(
        admin_id=admin_id,
        action="WITHDRAW_REJECT",
        payload_json={
            "withdrawal_id": w.id,
            "user_id": w.user_id,
            "amount_sum": w.amount_sum,
            "reason": reason,
        },
    )
    return w


@dbtx.atomic
def mark_paid(*, w: Withdrawal, admin_id: int, proof_url: str = "", note: str = "") -> Withdrawal:
    """
    PENDING/APPROVED → PAID
    - Qo'lda yuborilgan to'lovni yakuniylashtirish
    - AdminLog yozish (proof_url bo'lsa, saqlanadi)
    - (Balans/yana tranzaksiya shart emas — hold allaqachon WITHDRAWAL sifatida yozilgan)
    """
    if w.status not in ("PENDING", "APPROVED"):
        raise ValidationError("PENDING/APPROVED ni PAID qilish mumkin.")

    w.status = "PAID"
    w.admin_id = admin_id
    extra = []
    if proof_url:
        extra.append(f"[proof] {proof_url}")
    if note:
        extra.append(f"[note] {note}")
    if extra:
        w.admin_note = ((w.admin_note or "") + "\n" + "\n".join(extra)).strip()
    w.updated_at = timezone.now()
    w.save(update_fields=["status", "admin_id", "admin_note", "updated_at"])

    AdminLog.objects.create(
        admin_id=admin_id,
        action="WITHDRAW_PAID",
        payload_json={
            "withdrawal_id": w.id,
            "user_id": w.user_id,
            "amount_sum": w.amount_sum,
            "proof_url": proof_url,
            "note": note,
        },
    )
    return w
