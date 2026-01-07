from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.html import format_html


class Office(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


class Diary(models.Model):
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
            models.UniqueConstraint(fields=["year", "sequence"], name="uniq_diary_year_seq"),
        ]
        ordering = ["-year", "-sequence"]
        indexes = [
            models.Index(fields=["year", "sequence"]),
            models.Index(fields=["diary_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.diary_no

    @property
    def diary_no(self) -> str:
        return f"{self.year}-{self.sequence:06d}"

    def movement_history_html(self) -> str:
        """
        Register-style single column history:
        - older destinations struck-through
        - last destination plain text
        """
        mvs = list(self.movements.all().order_by("action_datetime", "id"))
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


    def clean(self):
        super().clean()
        if self.no_of_folders < 0:
            raise ValidationError({"no_of_folders": "Must be 0 or more."})

    # ✅ ADDITIVE: keep Office table populated for autocomplete/search
    def save(self, *args, **kwargs):
        # Keep offices recorded (optional but very useful)
        if self.received_from and self.received_from.strip():
            Office.objects.get_or_create(name=self.received_from.strip())
        if self.marked_to and self.marked_to.strip():
            Office.objects.get_or_create(name=self.marked_to.strip())
        super().save(*args, **kwargs)

    @classmethod
    def create_with_next_number(cls, *, created_by, **fields) -> "Diary":
        """
        Safely creates a diary with the next sequence number for a year.
        Uses an atomic transaction + select_for_update lock on the year rows.
        """
        fields = dict(fields)  # make mutable copy

        today = timezone.localdate()
        raw_year = fields.pop("year", None)
        year = int(raw_year) if raw_year else today.year

        with transaction.atomic():
            last_seq = (
                cls.objects.select_for_update()
                .filter(year=year)
                .aggregate(m=Max("sequence"))
                .get("m")
            )
            next_seq = (last_seq or 0) + 1

            diary = cls.objects.create(
                year=year,
                sequence=next_seq,
                created_by=created_by,
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
            Office.objects.get_or_create(name=self.from_office.strip())

        if self.to_office and self.to_office.strip():
            Office.objects.get_or_create(name=self.to_office.strip())

        super().save(*args, **kwargs)
