from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone


class Diary(models.Model):
    # Year-wise numbering
    year = models.PositiveIntegerField(db_index=True)
    sequence = models.PositiveIntegerField(db_index=True)

    # Access-like fields
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
    status = models.CharField(max_length=50, default="Pending")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="diaries_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["year", "sequence"], name="uniq_diary_year_seq"),
        ]
        ordering = ["-year", "-sequence"]

    @property
    def diary_no(self) -> str:
        return f"{self.year}-{self.sequence:06d}"

    @classmethod
    def create_with_next_number(cls, *, created_by, **fields):
        today = timezone.localdate()
        year = fields.get("year") or today.year
        fields["year"] = year

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
    diary = models.ForeignKey(Diary, on_delete=models.CASCADE, related_name="movements")

    # Copy for easier reporting (you asked)
    year = models.PositiveIntegerField(db_index=True)
    sequence = models.PositiveIntegerField(db_index=True)

    from_office = models.CharField(max_length=255, blank=True, default="")
    to_office = models.CharField(max_length=255, blank=True, default="")

    action_type = models.CharField(max_length=50)  # Created/Marked/Forwarded/Returned/Closed/Disposed
    action_datetime = models.DateTimeField(default=timezone.now)

    remarks = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movements_created"
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["action_datetime", "id"]
