import csv
import json
from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from django.contrib import admin, messages


from .models import (
    User, UserPhone, Project, Vote, OtpAttempt, Referral,
    Transaction, Withdrawal, AdminLog, SeleniumJob, Channel, Setting, ExportJob,RequiredChannel
)

# ==============================
# Admin site branding
# ==============================
admin.site.site_header = "OpenBudget Admin"
admin.site.site_title = "OpenBudget Admin"
admin.site.index_title = "Boshqaruv paneli"

# ==============================
# Helpers & Mixins
# ==============================

def uzs(n):
    """Raqamni vergul bilan ajratib (1,234,567) so'm ko'rinishida chiqarish uchun matn qaytaradi."""
    return f"{(n or 0):,}"



@admin.register(RequiredChannel)
class RequiredChannelAdmin(admin.ModelAdmin):
    """
    Minimal, ishonchli va qulay admin:
    - Jadvalda asosiy maydonlar
    - Tez tahrirlash: is_active, priority
    - Oddiy qidiruv va filtrlar
    - Ikki action: Activate / Deactivate
    - Hech qanday murakkab render yoki nozik hiyla yo'q — sindirish qiyin :)
    """

    # Jadval ko'rinishi
    list_display = ("id", "title", "chat_id", "invite_link", "is_active", "priority", "created_at")
    list_display_links = ("id", "title")
    list_editable = ("is_active", "priority")
    ordering = ("priority", "id")

    # Qidiruv va filtrlar
    search_fields = ("title", "chat_id", "invite_link")
    list_filter = ("is_active",)
    date_hierarchy = "created_at"

    # Form ko'rinishi — soddalashtirilgan
    readonly_fields = ("created_at",)
    fields = ("title", "chat_id", "invite_link", "is_active", "priority", "created_at")

    # Eng kerakli 2 ta action
    actions = ("activate", "deactivate")

    @admin.action(description="Faollashtirish")
    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} ta kanal faollashtirildi.", level=messages.SUCCESS)

    @admin.action(description="Faolsizlantirish")
    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} ta kanal faolsizlantirildi.", level=messages.SUCCESS)

    # Mayda, ammo foydali: invite_linkni tozalash (xatoliklarni kamaytiradi)
    def save_model(self, request, obj, form, change):
        if obj.invite_link:
            obj.invite_link = obj.invite_link.strip()
            # ixtiyoriy: agar @username kiritsa, t.me/username ko'rinishiga keltirish
            if obj.invite_link.startswith('@'):
                obj.invite_link = 'https://t.me/' + obj.invite_link.lstrip('@')
        super().save_model(request, obj, form, change)










class ExportCsvMixin:
    """Changelist tanlangan obyektlarni CSV eksport qilish actioni."""
    csv_filename_prefix = "export"

    def export_as_csv(self, request: HttpRequest, queryset):
        meta = self.model._meta
        field_names = [f.name for f in meta.fields]

        response = HttpResponse(content_type="text/csv")
        timestamp = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        response["Content-Disposition"] = (
            f'attachment; filename="{self.csv_filename_prefix}_{meta.model_name}_{timestamp}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = [getattr(obj, field, "") for field in field_names]
            writer.writerow(row)
        return response

    export_as_csv.short_description = "Tanlanganlarni CSV qilib yuklab olish"


class StatsOnChangelistMixin:
    """Changelist tepasida tezkor statistikani ko‘rsatish."""

    def changelist_view(self, request, extra_context=None):
        context = extra_context or {}
        context["quick_stats"] = self.get_quick_stats()
        return super().changelist_view(request, extra_context=context)

    def get_quick_stats(self) -> dict:
        """Har bir ModelAdmin o‘ziga mos qilib override qiladi."""
        return {}


def colored_bool(value: bool, true="✅", false="❌"):
    return format_html('<b style="color:{}">{}</b>', "green" if value else "crimson", true if value else false)


def colored_status(value: str):
    color = "gray"
    if value in {"PENDING", "OTP_REQUIRED"}:
        color = "orange"
    if value in {"PROCESSING", "APPROVED"}:
        color = "blue"
    if value in {"SUCCESS", "PAID"}:
        color = "green"
    if value in {"FAILED", "REJECTED", "CANCELED"}:
        color = "crimson"
    return format_html('<b style="color:{}">{}</b>', color, value)


# Dinamik admin change URL generator (app label/ model name hardcode qilmaslik uchun)

def admin_change_url(obj) -> str:
    return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change", args=[obj.pk])


# ==============================
# Custom Filters
# ==============================
class TodayCreatedFilter(admin.SimpleListFilter):
    title = "Bugun yaratilgan"
    parameter_name = "today"

    def lookups(self, request, model_admin):
        return (("yes", "Ha"), ("no", "Yo‘q"))

    def queryset(self, request, queryset):
        today = timezone.localdate()  # TIME_ZONE hisobga olinadi
        if self.value() == "yes":
            return queryset.filter(created_at__date=today)
        if self.value() == "no":
            return queryset.exclude(created_at__date=today)
        return queryset


# ==============================
# Inlines
# ==============================
class UserPhoneInline(admin.TabularInline):
    model = UserPhone
    extra = 0
    can_delete = False
    readonly_fields = ("phone_e164", "phone_snapshot", "created_at")
    show_change_link = False


class VoteOtpInline(admin.TabularInline):
    model = OtpAttempt
    extra = 0
    can_delete = False
    readonly_fields = ("code_entered", "result", "created_at")
    show_change_link = False


class VoteSeleniumInline(admin.TabularInline):
    model = SeleniumJob
    extra = 0
    can_delete = False
    readonly_fields = ("status", "node", "timings", "error", "created_at")
    show_change_link = False


# ==============================
# User stats helpers (for charts)
# ==============================
class _UserStats:
    @staticmethod
    def _date_range(days: int):
        today = timezone.localdate()
        start = today - timedelta(days=days - 1)
        return start, today

    @staticmethod
    def signups_last(days: int = 30):
        start, end = _UserStats._date_range(days)
        qs = (
            User.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("user_id"))
            .order_by("day")
        )
        mapping = {r["day"]: r["c"] for r in qs}
        labels, data = [], []
        d = start
        while d <= end:
            labels.append(d.strftime("%Y-%m-%d"))
            data.append(mapping.get(d, 0))
            d += timedelta(days=1)
        return labels, data

    @staticmethod
    def bans_last(days: int = 30):
        start, end = _UserStats._date_range(days)
        qs = (
            AdminLog.objects.filter(action="USER_DEACTIVATE", created_at__date__gte=start, created_at__date__lte=end)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(c=Count("id"))
            .order_by("day")
        )
        mapping = {r["day"]: r["c"] for r in qs}
        labels, data = [], []
        d = start
        while d <= end:
            labels.append(d.strftime("%Y-%m-%d"))
            data.append(mapping.get(d, 0))
            d += timedelta(days=1)
        return labels, data

    @staticmethod
    def headline():
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())  # dushanba
        month_start = today.replace(day=1)

        total = User.objects.count()
        active = User.objects.filter(active=True).count()
        banned = total - active

        new_today = User.objects.filter(created_at__date=today).count()
        new_week = User.objects.filter(created_at__date__gte=week_start).count()
        new_month = User.objects.filter(created_at__date__gte=month_start).count()

        bans_today = AdminLog.objects.filter(action="USER_DEACTIVATE", created_at__date=today).count()
        bans_week = AdminLog.objects.filter(action="USER_DEACTIVATE", created_at__date__gte=week_start).count()
        bans_month = AdminLog.objects.filter(action="USER_DEACTIVATE", created_at__date__gte=month_start).count()

        langs = list(User.objects.values("language").annotate(c=Count("user_id")).order_by("-c"))

        return {
            "total": total,
            "active": active,
            "banned": banned,
            "new_today": new_today,
            "new_week": new_week,
            "new_month": new_month,
            "bans_today": bans_today,
            "bans_week": bans_week,
            "bans_month": bans_month,
            "languages": langs,
        }


# ==============================
# ModelAdmins
# ==============================
@admin.register(User)
class UserAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = (
        "user_id", "username", "full_name", "active_colored", "language",
        "balance_sum", "created_at",
        "votes_count_display", "withdraw_sum_display",
    )
    list_filter = ("language", "active", TodayCreatedFilter)
    search_fields = ("user_id", "username", "full_name")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    inlines = [UserPhoneInline]
    actions = ["export_as_csv", "activate_users", "deactivate_users"]

    # Pro stats panel (template)
    change_list_template = "change_list.html"

    csv_filename_prefix = "users"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Annotate with stats
        return qs.annotate(
            votes_count=Count("votes", distinct=True),
            withdraw_paid_sum=Sum("withdrawals__amount_sum", filter=Q(withdrawals__status="PAID")),
        )

    def votes_count_display(self, obj):
        return obj.votes_count or 0

    votes_count_display.short_description = "Votes"

    def withdraw_sum_display(self, obj):
        val = obj.withdraw_paid_sum or 0
        return format_html("<b>{}</b> so‘m", uzs(val))

    withdraw_sum_display.short_description = "Paid out"

    def active_colored(self, obj):
        return colored_bool(obj.active)

    active_colored.short_description = "Active"

    # === Actions with AdminLog (ban stats works) ===
    def activate_users(self, request, queryset):
        updated = queryset.update(active=True)
        AdminLog.objects.create(
            admin_id=getattr(request.user, "id", None) or 0,
            action="USER_ACTIVATE",
            payload_json={"ids": list(queryset.values_list("pk", flat=True)), "count": updated},
        )
        self.message_user(request, f"{updated} ta foydalanuvchi faollashtirildi.", messages.SUCCESS)

    activate_users.short_description = "Faollashtirish"

    def deactivate_users(self, request, queryset):
        updated = queryset.update(active=False)
        AdminLog.objects.create(
            admin_id=getattr(request.user, "id", None) or 0,
            action="USER_DEACTIVATE",
            payload_json={"ids": list(queryset.values_list("pk", flat=True)), "count": updated},
        )
        self.message_user(request, f"{updated} ta foydalanuvchi faol emas qilindi.", messages.WARNING)

    deactivate_users.short_description = "Faol emas qilish"

    # === Stats context (for template) ===
    def changelist_view(self, request, extra_context=None):
        ctx = extra_context or {}
        headline = _UserStats.headline()
        s_labels, s_data = _UserStats.signups_last(30)
        b_labels, b_data = _UserStats.bans_last(30)

        ctx.update({
            "headline": headline,
            "chart_signups_labels": mark_safe(json.dumps(s_labels)),
            "chart_signups_data": mark_safe(json.dumps(s_data)),
            "chart_bans_labels": mark_safe(json.dumps(b_labels)),
            "chart_bans_data": mark_safe(json.dumps(b_data)),
            "languages": headline["languages"],
        })
        return super().changelist_view(request, extra_context=ctx)

    def get_quick_stats(self) -> dict:
        return {
            "Jami foydalanuvchi": User.objects.count(),
            "Faol foydalanuvchi": User.objects.filter(active=True).count(),
            "Bugun qo‘shilgan": User.objects.filter(
                created_at__date=timezone.localdate()
            ).count(),
            "Jami to‘langan (PAID)": (Withdrawal.objects.filter(status="PAID").aggregate(s=Sum("amount_sum")) or {}).get("s") or 0,
        }


@admin.register(UserPhone)
class UserPhoneAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "phone_e164", "phone_snapshot", "created_at")
    list_filter = (TodayCreatedFilter,)
    search_fields = ("phone_e164", "phone_snapshot", "user__username")
    readonly_fields = ("created_at",)
    csv_filename_prefix = "userphones"


@admin.register(Project)
class ProjectAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = (
        "id", "title", "is_active_col", "reward_sum_fmt",
        "target_votes", "created_at", "votes_success", "votes_total",
        "url_link"
    )
    list_filter = ("is_active", "category", TodayCreatedFilter)
    search_fields = ("title", "ob_project_id", "region", "district", "category")
    readonly_fields = ("created_at",)
    actions = ["export_as_csv", "activate", "deactivate"]
    csv_filename_prefix = "projects"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            votes_total_count=Count("votes"),
            votes_success_count=Count("votes", filter=Q(votes__status="SUCCESS")),
        )

    def is_active_col(self, obj):
        return colored_bool(obj.is_active)

    is_active_col.short_description = "Active"

    def reward_sum_fmt(self, obj):
        return format_html("<b>{}</b> so‘m", uzs(obj.reward_sum))

    reward_sum_fmt.short_description = "Reward"

    def votes_total(self, obj):
        return obj.votes_total_count or 0

    votes_total.short_description = "Votes (all)"

    def votes_success(self, obj):
        return obj.votes_success_count or 0

    votes_success.short_description = "Votes (SUCCESS)"

    def url_link(self, obj):
        return format_html('<a href="{}" target="_blank">ochish</a>', obj.url)

    url_link.short_description = "Havola"

    def activate(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} ta loyiha aktiv qilindi.", messages.SUCCESS)

    activate.short_description = "Aktiv qilish"

    def deactivate(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} ta loyiha deaktiv qilindi.", messages.WARNING)

    deactivate.short_description = "Deaktiv qilish"

    def get_quick_stats(self) -> dict:
        return {
            "Aktiv loyihalar": Project.objects.filter(is_active=True).count(),
            "Jami loyihalar": Project.objects.count(),
            "SUCCESS ovozlar": Vote.objects.filter(status="SUCCESS").count(),
        }


@admin.register(Vote)
class VoteAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = (
        "id", "user_link", "project_link", "status_col", "attempt_count",
        "phone_snapshot", "created_at",
        "proof_short", "error_short",
    )
    list_filter = ("status", TodayCreatedFilter)
    search_fields = ("phone_snapshot", "ob_vote_id", "user__username", "project__title")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    inlines = [VoteOtpInline, VoteSeleniumInline]
    actions = ["export_as_csv", "mark_success", "mark_failed", "mark_processing"]
    csv_filename_prefix = "votes"

    def user_link(self, obj):
        try:
            url = admin_change_url(obj.user)
            return format_html('<a href="{}">{}</a>', url, obj.user_id)
        except Exception:
            return obj.user_id

    user_link.short_description = "User"

    def project_link(self, obj):
        try:
            url = admin_change_url(obj.project)
            return format_html('<a href="{}">{}</a>', url, obj.project_id)
        except Exception:
            return obj.project_id

    project_link.short_description = "Project"

    def status_col(self, obj):
        return colored_status(obj.status)

    status_col.short_description = "Status"

    def proof_short(self, obj):
        if obj.proof_screenshot_path:
            return format_html('<a href="{}" target="_blank">ko‘rish</a>', obj.proof_screenshot_path)
        return "-"

    proof_short.short_description = "Proof"

    def error_short(self, obj):
        return (obj.error_message[:60] + "…") if obj.error_message and len(obj.error_message) > 60 else (obj.error_message or "-")

    error_short.short_description = "Xato"

    def mark_success(self, request, queryset):
        n = queryset.update(status="SUCCESS")
        self.message_user(request, f"{n} ta ovoz SUCCESS qilindi.", messages.SUCCESS)

    mark_success.short_description = "Status: SUCCESS"

    def mark_failed(self, request, queryset):
        n = queryset.update(status="FAILED")
        self.message_user(request, f"{n} ta ovoz FAILED qilindi.", messages.ERROR)

    mark_failed.short_description = "Status: FAILED"

    def mark_processing(self, request, queryset):
        n = queryset.update(status="PROCESSING")
        self.message_user(request, f"{n} ta ovoz PROCESSING qilindi.", messages.INFO)

    mark_processing.short_description = "Status: PROCESSING"

    def get_quick_stats(self) -> dict:
        qs = Vote.objects.all()
        today = timezone.localdate()
        return {
            "Bugungi PENDING": qs.filter(status="PENDING", created_at__date=today).count(),
            "Bugungi SUCCESS": qs.filter(status="SUCCESS", created_at__date=today).count(),
            "Jami SUCCESS": qs.filter(status="SUCCESS").count(),
            "Jami FAILED": qs.filter(status="FAILED").count(),
        }


@admin.register(OtpAttempt)
class OtpAttemptAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "vote_id", "code_entered", "result", "created_at")
    list_filter = ("result", TodayCreatedFilter)
    search_fields = ("code_entered", "vote__id")
    readonly_fields = ("created_at",)
    csv_filename_prefix = "otp_attempts"


@admin.register(Referral)
class ReferralAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = ("id", "referrer_user_id", "referred_user_id", "status_col", "bonus_sum_fmt", "created_at")
    list_filter = ("status", TodayCreatedFilter)
    search_fields = ("referrer_user__username", "referred_user__username", "referrer_user_id", "referred_user_id")
    readonly_fields = ("created_at",)
    actions = ["export_as_csv", "mark_qualified", "mark_paid", "mark_rejected"]
    csv_filename_prefix = "referrals"

    def status_col(self, obj):
        return colored_status(obj.status)

    status_col.short_description = "Status"

    def bonus_sum_fmt(self, obj):
        return format_html("<b>{}</b> so‘m", uzs(obj.bonus_sum))

    bonus_sum_fmt.short_description = "Bonus"

    def mark_qualified(self, request, queryset):
        n = queryset.update(status="QUALIFIED")
        self.message_user(request, f"{n} ta referral QUALIFIED qilindi.", messages.INFO)

    mark_qualified.short_description = "Status: QUALIFIED"

    def mark_paid(self, request, queryset):
        n = queryset.update(status="PAID")
        self.message_user(request, f"{n} ta referral PAID qilindi.", messages.SUCCESS)

    mark_paid.short_description = "Status: PAID"

    def mark_rejected(self, request, queryset):
        n = queryset.update(status="REJECTED")
        self.message_user(request, f"{n} ta referral REJECTED qilindi.", messages.ERROR)

    mark_rejected.short_description = "Status: REJECTED"

    def get_quick_stats(self) -> dict:
        qs = Referral.objects.all()
        return {
            "Jami referrals": qs.count(),
            "QUALIFIED": qs.filter(status="QUALIFIED").count(),
            "PAID": qs.filter(status="PAID").count(),
        }


@admin.register(Transaction)
class TransactionAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = ("id", "user_id", "type_col", "amount_fmt", "ref_id", "created_at")
    list_filter = ("type", TodayCreatedFilter)
    search_fields = ("user__username", "user_id", "ref_id")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at",)
    actions = ["export_as_csv"]
    csv_filename_prefix = "transactions"

    def type_col(self, obj):
        return colored_status(obj.type)

    type_col.short_description = "Type"

    def amount_fmt(self, obj):
        amt = obj.amount_sum or 0
        color = "crimson" if amt < 0 else "green"
        return format_html('<b style="color:{}">{}</b> so‘m', color, uzs(amt))

    amount_fmt.short_description = "Miqdor"

    def get_quick_stats(self) -> dict:
        qs = Transaction.objects.all()
        return {
            "Jami tranzaksiyalar": qs.count(),
            "Daromad (REWARD+REFERRAL)": (qs.filter(type__in=["REWARD", "REFERRAL"]).aggregate(s=Sum("amount_sum")) or {}).get("s") or 0,
            "Chiqim (WITHDRAWAL+PENALTY)": (qs.filter(type__in=["WITHDRAWAL", "PENALTY"]).aggregate(s=Sum("amount_sum")) or {}).get("s") or 0,
        }


@admin.register(Withdrawal)
class WithdrawalAdmin(ExportCsvMixin, StatsOnChangelistMixin, admin.ModelAdmin):
    list_display = (
        "id", "user_id", "amount_fmt", "method", "status_col",
        "destination_masked", "updated_at", "created_at",
    )
    list_filter = ("status", "method", TodayCreatedFilter)
    search_fields = ("user__username", "user_id", "destination_masked")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")
    actions = ["export_as_csv", "approve", "reject", "mark_paid"]
    csv_filename_prefix = "withdrawals"

    def status_col(self, obj):
        return colored_status(obj.status)

    status_col.short_description = "Status"

    def amount_fmt(self, obj):
        return format_html("<b>{}</b> so‘m", uzs(obj.amount_sum))

    amount_fmt.short_description = "Miqdor"

    def approve(self, request, queryset):
        n = queryset.filter(status="PENDING").update(status="APPROVED")
        self.message_user(request, f"{n} ta so‘rov APPROVED qilindi.", messages.INFO)

    approve.short_description = "APPROVE (tanlangan PENDING)"

    def reject(self, request, queryset):
        n = queryset.exclude(status="PAID").update(status="REJECTED")
        self.message_user(request, f"{n} ta so‘rov REJECTED qilindi.", messages.WARNING)

    reject.short_description = "REJECT (PAID bo‘lmaganlar)"

    def mark_paid(self, request, queryset):
        n = queryset.exclude(status="PAID").update(status="PAID")
        self.message_user(request, f"{n} ta so‘rov PAID qilindi.", messages.SUCCESS)

    mark_paid.short_description = "PAID qilish"

    def get_quick_stats(self) -> dict:
        qs = Withdrawal.objects.all()
        return {
            "PENDING": qs.filter(status="PENDING").count(),
            "APPROVED": qs.filter(status="APPROVED").count(),
            "PAID": qs.filter(status="PAID").count(),
            "REJECTED": qs.filter(status="REJECTED").count(),
        }


@admin.register(AdminLog)
class AdminLogAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "admin_id", "action", "created_at")
    search_fields = ("action", "admin_id")
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "payload_json")
    actions = ["export_as_csv"]
    csv_filename_prefix = "adminlogs"


@admin.register(SeleniumJob)
class SeleniumJobAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "vote_id", "status_col", "node", "created_at", "error_short")
    list_filter = ("status", TodayCreatedFilter)
    search_fields = ("vote__id", "node")
    readonly_fields = ("created_at", "timings", "error")
    actions = ["export_as_csv", "mark_running", "mark_done", "mark_failed"]
    csv_filename_prefix = "seleniumjobs"

    def status_col(self, obj):
        return colored_status(obj.status)

    status_col.short_description = "Status"

    def error_short(self, obj):
        return (obj.error[:60] + "…") if obj.error and len(obj.error) > 60 else (obj.error or "-")

    error_short.short_description = "Xato"

    def mark_running(self, request, queryset):
        n = queryset.update(status="RUNNING")
        self.message_user(request, f"{n} ta job RUNNING qilindi.", messages.INFO)

    mark_running.short_description = "Status: RUNNING"

    def mark_done(self, request, queryset):
        n = queryset.update(status="DONE")
        self.message_user(request, f"{n} ta job DONE qilindi.", messages.SUCCESS)

    mark_done.short_description = "Status: DONE"

    def mark_failed(self, request, queryset):
        n = queryset.update(status="FAILED")
        self.message_user(request, f"{n} ta job FAILED qilindi.", messages.ERROR)

    mark_failed.short_description = "Status: FAILED"


@admin.register(Channel)
class ChannelAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "chat_id", "type", "title", "is_active_col", "created_at")
    list_filter = ("type", "is_active", TodayCreatedFilter)
    search_fields = ("chat_id", "title")
    readonly_fields = ("created_at",)
    actions = ["export_as_csv", "activate", "deactivate"]
    csv_filename_prefix = "channels"

    def is_active_col(self, obj):
        return colored_bool(obj.is_active)

    is_active_col.short_description = "Active"

    def activate(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, f"{n} ta kanal aktiv.", messages.SUCCESS)

    activate.short_description = "Aktiv qilish"

    def deactivate(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f"{n} ta kanal deaktiv.", messages.WARNING)

    deactivate.short_description = "Deaktiv qilish"


@admin.register(Setting)
class SettingAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "key", "active_project_link", "default_reward_sum", "allow_multiple_active_projects", "created_at")
    search_fields = ("key",)
    readonly_fields = ("created_at",)
    actions = ["export_as_csv"]
    csv_filename_prefix = "settings"

    def active_project_link(self, obj):
        if obj.active_project_id and obj.active_project:
            try:
                url = admin_change_url(obj.active_project)
                return format_html('<a href="{}">#{}</a>', url, obj.active_project_id)
            except Exception:
                pass
        return "-"

    active_project_link.short_description = "Active project"


@admin.register(ExportJob)
class ExportJobAdmin(ExportCsvMixin, admin.ModelAdmin):
    list_display = ("id", "admin_id", "kind", "status_col", "file_link", "error_short", "created_at")
    list_filter = ("kind", "status", TodayCreatedFilter)
    search_fields = ("admin_id", "kind")
    readonly_fields = ("created_at",)
    actions = ["export_as_csv", "mark_running", "mark_done", "mark_failed"]
    csv_filename_prefix = "exportjobs"

    def status_col(self, obj):
        return colored_status(obj.status)

    status_col.short_description = "Status"

    def file_link(self, obj):
        if obj.file_path:
            return format_html('<a href="{}" target="_blank">yuklab olish</a>', obj.file_path)
        return "-"

    file_link.short_description = "Fayl"

    def error_short(self, obj):
        return (obj.error[:60] + "…") if obj.error and len(obj.error) > 60 else (obj.error or "-")

    error_short.short_description = "Xato"

    def mark_running(self, request, queryset):
        n = queryset.update(status="RUNNING")
        self.message_user(request, f"{n} ta export RUNNING qilindi.", messages.INFO)

    mark_running.short_description = "Status: RUNNING"

    def mark_done(self, request, queryset):
        n = queryset.update(status="DONE")
        self.message_user(request, f"{n} ta export DONE qilindi.", messages.SUCCESS)

    mark_done.short_description = "Status: DONE"

    def mark_failed(self, request, queryset):
        n = queryset.update(status="FAILED")
        self.message_user(request, f"{n} ta export FAILED qilindi.", messages.ERROR)

    mark_failed.short_description = {"Status: FAILED"}
