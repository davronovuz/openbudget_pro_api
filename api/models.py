from django.db import models
from django.utils import timezone


# ======== Helpers: CHOICES ========
LANG_CHOICES = (
    ("uz", "Uzbek"),
    ("ru", "Russian"),
    ("en", "English"),
)

VOTE_STATUS = (
    ("PENDING", "PENDING"),
    ("OTP_REQUIRED", "OTP_REQUIRED"),
    ("PROCESSING", "PROCESSING"),
    ("SUCCESS", "SUCCESS"),
    ("FAILED", "FAILED"),
)

OTP_RESULT = (
    ("OK", "OK"),
    ("WRONG", "WRONG"),
    ("EXPIRED", "EXPIRED"),
    ("ERROR", "ERROR"),
)

REFERRAL_STATUS = (
    ("PENDING", "PENDING"),
    ("QUALIFIED", "QUALIFIED"),
    ("PAID", "PAID"),
    ("REJECTED", "REJECTED"),
)

TXN_TYPE = (
    ("REWARD", "REWARD"),
    ("REFERRAL", "REFERRAL"),
    ("WITHDRAWAL", "WITHDRAWAL"),
    ("ADJUSTMENT", "ADJUSTMENT"),
    ("PENALTY", "PENALTY"),
)

WITHDRAW_STATUS = (
    ("PENDING", "PENDING"),
    ("APPROVED", "APPROVED"),
    ("PAID", "PAID"),
    ("REJECTED", "REJECTED"),
    ("CANCELED", "CANCELED"),
)

WITHDRAW_METHOD = (
    ("CARD", "CARD"),
    ("CLICK", "CLICK"),
    ("PAYME", "PAYME"),
    ("OTHER", "OTHER"),
)

JOB_STATUS = (
    ("QUEUED", "QUEUED"),
    ("RUNNING", "RUNNING"),
    ("DONE", "DONE"),
    ("FAILED", "FAILED"),
)

CHANNEL_TYPE = (
    ("PAYOUTS", "PAYOUTS"),
    ("ALERTS", "ALERTS"),
)

EXPORT_KIND = (
    ("USERS", "USERS"),
    ("VOTES", "VOTES"),
    ("WITHDRAWALS", "WITHDRAWALS"),
    ("PROJECTS", "PROJECTS"),
)

EXPORT_STATUS = (
    ("PENDING", "PENDING"),
    ("RUNNING", "RUNNING"),
    ("DONE", "DONE"),
    ("FAILED", "FAILED"),
)


class User(models.Model):
    user_id = models.BigIntegerField(primary_key=True)  # Telegram ID
    username = models.CharField(max_length=128, null=True, blank=True)
    full_name = models.CharField(max_length=128)
    active = models.BooleanField(default=True)
    language = models.CharField(max_length=10, choices=LANG_CHOICES, default="uz")
    balance_sum = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        managed = True
        db_table = "users"
        indexes = [
            models.Index(fields=["active"], name="ix_users_active"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.username or '-'}"


class UserPhone(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id", related_name="phones"
    )
    phone_e164 = models.CharField(max_length=24)
    phone_snapshot = models.CharField(max_length=24)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "userphones"
        indexes = [
            models.Index(fields=["phone_snapshot"], name="ix_userphone_snapshot"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "phone_e164"], name="uq_user_phone_per_user"
            ),
        ]


class Project(models.Model):
    id = models.AutoField(primary_key=True)
    ob_project_id = models.CharField(max_length=64)
    title = models.CharField(max_length=255)
    url = models.CharField(max_length=1024)
    region = models.CharField(max_length=128, null=True, blank=True)
    district = models.CharField(max_length=128, null=True, blank=True)
    category = models.CharField(max_length=128, null=True, blank=True)
    is_active = models.BooleanField(default=False)
    reward_sum = models.IntegerField(default=0)
    target_votes = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "projects"
        indexes = [
            models.Index(fields=["is_active"], name="ix_projects_active"),
            models.Index(fields=["category"], name="ix_projects_category"),
        ]

    def __str__(self) -> str:
        return f"[{self.id}] {self.title}"


class Vote(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id", related_name="votes"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, db_column="project_id", related_name="votes"
    )
    user_phone_id = models.IntegerField(null=True, blank=True)
    phone_snapshot = models.CharField(max_length=24)
    status = models.CharField(max_length=24, choices=VOTE_STATUS, default="PENDING")
    attempt_count = models.IntegerField(default=0)
    selenium_session_id = models.CharField(max_length=128, null=True, blank=True)
    ob_vote_id = models.CharField(max_length=64, null=True, blank=True)
    proof_screenshot_path = models.CharField(max_length=1024, null=True, blank=True)
    error_message = models.CharField(max_length=512, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        managed = True
        db_table = "votes"
        indexes = [
            models.Index(fields=["project", "status"], name="ix_votes_project_status"),
            models.Index(fields=["user"], name="ix_votes_user"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "phone_snapshot"], name="uq_vote_phone_per_project"
            ),
            models.UniqueConstraint(
                fields=["project", "user_phone_id"], name="uq_vote_userphone_per_project"
            ),
        ]


class OtpAttempt(models.Model):
    id = models.AutoField(primary_key=True)
    vote = models.ForeignKey(
        Vote, on_delete=models.CASCADE, db_column="vote_id", related_name="otp_attempts"
    )
    code_entered = models.CharField(max_length=16)
    result = models.CharField(max_length=16, choices=OTP_RESULT)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "otpattempts"


class Referral(models.Model):
    id = models.AutoField(primary_key=True)
    referrer_user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="referrer_user_id", related_name="referrals_made"
    )
    referred_user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="referred_user_id", related_name="referrals_received"
    )
    bonus_sum = models.IntegerField(default=0)
    status = models.CharField(max_length=16, choices=REFERRAL_STATUS, default="PENDING")
    reason = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "referrals"


class Transaction(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id", related_name="transactions"
    )
    type = models.CharField(max_length=16, choices=TXN_TYPE)
    amount_sum = models.IntegerField()      # UZS; negative for payouts/penalties
    ref_id = models.IntegerField(null=True, blank=True)  # e.g. vote_id / referral_id / withdrawal_id
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        managed = True
        db_table = "transactions"
        indexes = [
            models.Index(fields=["user", "created_at"], name="ix_txn_user_created"),
        ]


class Withdrawal(models.Model):
    id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, db_column="user_id", related_name="withdrawals"
    )
    amount_sum = models.IntegerField()
    method = models.CharField(max_length=16, choices=WITHDRAW_METHOD)
    destination_masked = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=WITHDRAW_STATUS, default="PENDING")
    admin_id = models.BigIntegerField(null=True, blank=True)
    admin_note = models.CharField(max_length=255, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "withdrawals"
        indexes = [
            models.Index(fields=["status"], name="ix_withdraw_status"),
        ]


class AdminLog(models.Model):
    id = models.AutoField(primary_key=True)
    admin_id = models.BigIntegerField()
    action = models.CharField(max_length=128)
    payload_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "adminlogs"


class SeleniumJob(models.Model):
    id = models.AutoField(primary_key=True)
    vote = models.ForeignKey(
        Vote, on_delete=models.CASCADE, db_column="vote_id", related_name="selenium_jobs"
    )
    status = models.CharField(max_length=16, choices=JOB_STATUS, default="QUEUED")
    node = models.CharField(max_length=64, null=True, blank=True)
    timings = models.JSONField(null=True, blank=True)
    error = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "seleniumjobs"


class Channel(models.Model):
    id = models.AutoField(primary_key=True)
    chat_id = models.BigIntegerField()
    type = models.CharField(max_length=16, choices=CHANNEL_TYPE)
    title = models.CharField(max_length=128, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "channels"


class Setting(models.Model):
    id = models.AutoField(primary_key=True)
    key = models.CharField(max_length=64, unique=True)
    active_project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, db_column="active_project_id"
    )
    default_reward_sum = models.IntegerField(default=0)
    allow_multiple_active_projects = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "settings"


class ExportJob(models.Model):
    id = models.AutoField(primary_key=True)
    admin_id = models.BigIntegerField(null=True)
    kind = models.CharField(max_length=32, choices=EXPORT_KIND)
    status = models.CharField(max_length=16, choices=EXPORT_STATUS, default="PENDING")
    params = models.JSONField(null=True, blank=True)
    file_path = models.CharField(max_length=1024, null=True, blank=True)
    error = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = True
        db_table = "exportjobs"