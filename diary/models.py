from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.html import format_html


def format_diary_number(sequence):
    return f'{sequence:05d}'


class Directorate(models.Model):
    name = models.CharField(max_length=255)
    code = models.SlugField(max_length=32, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        SYSTEM = 'system', 'System Administrator'
        ADMIN = 'admin', 'Directorate Administrator'
        OPERATOR = 'operator', 'Data Entry Operator'
        VIEWER = 'viewer', 'Viewer'
        AUDITOR = 'auditor', 'Auditor'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membership')
    directorate = models.ForeignKey(Directorate, null=True, blank=True, on_delete=models.PROTECT)
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(role='system') | models.Q(directorate__isnull=False), name='ordinary_user_has_directorate')]


class DirectorateSettings(models.Model):
    directorate = models.OneToOneField(Directorate, on_delete=models.CASCADE)
    report_title = models.CharField(max_length=255, blank=True)


class DiaryCounter(models.Model):
    directorate = models.ForeignKey(Directorate, on_delete=models.PROTECT)
    year = models.PositiveIntegerField()
    value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['directorate', 'year'], name='uniq_counter_directorate_year')]


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    directorate = models.ForeignKey(Directorate, null=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=64)
    record_id = models.CharField(max_length=64, blank=True)
    changes = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True)


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    started = models.DateTimeField(default=timezone.now)


class Office(models.Model):
    directorate = models.ForeignKey('Directorate', null=True, on_delete=models.PROTECT)
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=['directorate', 'name'], name='uniq_office_directorate_name')]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


class Diary(models.Model):
    directorate = models.ForeignKey('Directorate', null=True, on_delete=models.PROTECT)
    archived = models.BooleanField(default=False)
    class Status(models.TextChoices):
        PENDING = "Pending", "Pending"
        CREATED = "Created", "Created"
        MARKED = "Marked", "Marked"
        FORWARDED = "Forwarded", "Forwarded"
        RETURNED = "Returned", "Returned"
        CLOSED = "Closed", "Closed"
        DISPOSED = "Disposed", "Disposed"

    # Year-wise numbering
    year = models.PositiveIntegerField(db_index=True)
    sequence = models.PositiveIntegerField(db_index=True)

    diary_date = models.DateField(default=timezone.localdate)

    received_from = models.CharField(max_length=255, blank=True, default="")
    received_diary_no = models.CharField(max_length=100, blank=True, default="")
    file_letter = models.CharField(max_length=100, blank=True, default="")
    no_of_folders = models.PositiveIntegerField(default=0)
    service_included = models.BooleanField(default=False)

    subject = models.TextField(blank=True, default="")
    remarks = models.TextField(blank=True, default="")

    # Snapshot / current position
    marked_to = models.CharField(max_length=255, blank=True, default="")
    marked_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PENDING)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="diaries_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["directorate", "year", "sequence"], name="uniq_directorate_year_seq"),
        ]
        ordering = ["-year", "-sequence"]
        indexes = [
            models.Index(fields=['directorate', 'year', 'created_at']),
            models.Index(fields=["year", "sequence"]),
            models.Index(fields=["diary_date"]),
            models.Index(fields=["status"]),
            models.Index(fields=["received_diary_no"]),
            models.Index(fields=["received_from"]),
            models.Index(fields=["file_letter"]),
            models.Index(fields=["marked_to"]),
        ]


    def __str__(self) -> str:
        return self.diary_no

    @property
    def diary_no(self) -> str:
        return format_diary_number(self.sequence)

    @property
    def diary_no_short(self) -> str:
        """Compact diary number used for reports: no zero-padding on sequence."""
        return self.diary_no

    def movement_history_html(self) -> str:
        """
        Register-style single column history:
        - older destinations struck-through
        - last destination plain text
        """
        mvs = sorted(self.movements.all(), key=lambda movement: (movement.action_datetime, movement.pk))
        if not mvs:
            return "-"

        last_idx = len(mvs) - 1

        def _label(mv: "DiaryMovement") -> str:
            d = timezone.localtime(mv.action_datetime).date()
            # change dd-mm to dd-mm-yyyy if you want:
            # return f"{mv.to_office} {d.strftime('%d-%m-%Y')}"
            return f"{(mv.to_office or '-') } {d.strftime('%d-%m')}"

        parts = []
        for i, mv in enumerate(mvs):
            label = _label(mv)
            if i != last_idx:
                parts.append(format_html("<s>{}</s>", label))
            else:
                parts.append(format_html("{}", label))

        # Join with " / " like the physical register
        out = parts[0]
        sep = format_html(" / ")
        for p in parts[1:]:
            out = format_html("{}{}{}", out, sep, p)
        return out

    def movement_history_plain(self) -> str:
        """
        Plain-text movement history suitable for web tables where HTML strike
        formatting is undesirable. Older entries are left as plain text but
        are not struck-through; entries are joined with ' / '.
        """
        mvs = sorted(self.movements.all(), key=lambda movement: (movement.action_datetime, movement.pk))
        if not mvs:
            return "-"

        parts = []
        for mv in mvs:
            d = timezone.localtime(mv.action_datetime).date()
            parts.append(f"{(mv.to_office or '-') } {d.strftime('%d-%m')}")

        return " / ".join(parts)



    def clean(self):
        super().clean()
        if self.no_of_folders < 0:
            raise ValidationError({"no_of_folders": "Must be 0 or more."})

    # ✅ ADDITIVE: keep Office table populated for autocomplete/search
    def save(self, *args, **kwargs):
        # Keep offices recorded (optional but very useful)
        if self.received_from and self.received_from.strip():
            Office.objects.get_or_create(directorate=self.directorate, name=self.received_from.strip())
        if self.marked_to and self.marked_to.strip():
            Office.objects.get_or_create(directorate=self.directorate, name=self.marked_to.strip())
        super().save(*args, **kwargs)

    @classmethod
    def create_with_next_number(cls, *, created_by, **fields) -> "Diary":
        """
        Allocate using a unique directorate/year counter row locked until commit.
        get_or_create handles concurrent initialization of the first year's row.
        """
        fields = dict(fields)  # make mutable copy

        today = timezone.localdate()
        from .access import membership_for
        membership = membership_for(created_by)
        if not membership or membership.role not in ('admin', 'operator') or not membership.directorate_id or not membership.directorate.is_active:
            raise ValidationError('An active directorate membership is required.')
        fields.pop('directorate', None)
        fields.pop('year', None)
        year = today.year

        with transaction.atomic():
            counter, _ = DiaryCounter.objects.get_or_create(directorate=membership.directorate, year=year)
            counter = DiaryCounter.objects.select_for_update().get(pk=counter.pk)
            counter.value += 1
            counter.save(update_fields=['value'])
            next_seq = counter.value

            diary = cls.objects.create(
                year=year,
                sequence=next_seq,
                created_by=created_by,
                directorate=membership.directorate,
                **fields,
            )

        return diary


class DiaryMovement(models.Model):
    class ActionType(models.TextChoices):
        CREATED = "Created", "Created"
        MARKED = "Marked", "Marked"
        FORWARDED = "Forwarded", "Forwarded"
        RETURNED = "Returned", "Returned"
        CLOSED = "Closed", "Closed"
        DISPOSED = "Disposed", "Disposed"

    diary = models.ForeignKey(Diary, on_delete=models.CASCADE, related_name="movements")

    # Copy for easier reporting
    year = models.PositiveIntegerField(db_index=True, blank=True, null=True)
    sequence = models.PositiveIntegerField(db_index=True, blank=True, null=True)

    from_office = models.CharField(max_length=255, blank=True, default="")
    to_office = models.CharField(max_length=255, blank=True, default="")

    action_type = models.CharField(max_length=50, choices=ActionType.choices)
    action_datetime = models.DateTimeField(default=timezone.now)

    remarks = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements_created"
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["action_datetime", "id"]
        indexes = [
            models.Index(fields=["year", "sequence"]),
            models.Index(fields=["action_type"]),
            models.Index(fields=["action_datetime"]),
        ]

    def __str__(self) -> str:
        return f"{self.diary.diary_no} - {self.action_type}"

    def save(self, *args, **kwargs):
        # Always keep year/sequence in sync with diary
        if self.diary_id:
            self.year = self.diary.year
            self.sequence = self.diary.sequence

        # ✅ ADDITIVE: record offices automatically for autocomplete / indexing
        if self.from_office and self.from_office.strip():
            Office.objects.get_or_create(directorate=self.diary.directorate, name=self.from_office.strip())

        if self.to_office and self.to_office.strip():
            Office.objects.get_or_create(directorate=self.diary.directorate, name=self.to_office.strip())

        super().save(*args, **kwargs)


class AppConfig(models.Model):
    """
    Singleton model to store deployment-specific configuration.
    Only one instance should exist.
    """
    directorate_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Name of the directorate for PDF reports. If blank, reports will use generic title."
    )
    port = models.PositiveIntegerField(
        default=8000,
        help_text="Port number for the Django application."
    )
    host = models.CharField(
        max_length=255,
        default="0.0.0.0",
        help_text="Host/IP address to bind the application to."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "App Configuration"
        verbose_name_plural = "App Configuration"

    def save(self, *args, **kwargs):
        # Enforce singleton
        if self.pk is None and AppConfig.objects.exists():
            # Update the existing record instead
            existing = AppConfig.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    def __str__(self):
        return f"App Config - Directorate: {self.directorate_name or '(not set)'}"

    @classmethod
    def get_config(cls):
        """Get or create the singleton config instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
