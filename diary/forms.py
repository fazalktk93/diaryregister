from __future__ import annotations

from django import forms
from django.utils import timezone
from django.utils.timezone import is_naive, make_aware

from .models import Diary, DiaryMovement


BOOTSTRAP_INPUT_CLASS = "form-control"
BOOTSTRAP_SELECT_CLASS = "form-select"


class DiaryCreateForm(forms.ModelForm):
    class Meta:
        model = Diary
        fields = [
            "diary_date",
            "received_from",
            "received_diary_no",
            "file_letter",
            "no_of_folders",
            "subject",
            "remarks",
        ]
        widgets = {
            "diary_date": forms.DateInput(attrs={"type": "date", "class": BOOTSTRAP_INPUT_CLASS}),
            "received_from": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS}),
            "received_diary_no": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS}),
            "file_letter": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS}),
            "no_of_folders": forms.NumberInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "min": 0}),
            "subject": forms.Textarea(attrs={"class": BOOTSTRAP_INPUT_CLASS, "rows": 3}),
            "remarks": forms.Textarea(attrs={"class": BOOTSTRAP_INPUT_CLASS, "rows": 3}),
        }

    diary_date = forms.DateField(initial=timezone.localdate, required=True)


class MovementCreateForm(forms.ModelForm):
    class Meta:
        model = DiaryMovement
        fields = ["from_office", "to_office", "action_type", "action_datetime", "remarks"]
        widgets = {
            "from_office": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS}),
            "to_office": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS}),
            "action_type": forms.Select(attrs={"class": BOOTSTRAP_SELECT_CLASS}),
            "action_datetime": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": BOOTSTRAP_INPUT_CLASS}
            ),
            "remarks": forms.Textarea(attrs={"class": BOOTSTRAP_INPUT_CLASS, "rows": 3}),
        }

    def clean_action_datetime(self):
        dt = self.cleaned_data.get("action_datetime")
        if not dt:
            return timezone.now()
        # datetime-local often returns naive datetime
        if is_naive(dt):
            return make_aware(dt, timezone.get_current_timezone())
        return dt

    def clean(self):
        cleaned = super().clean()
        to_office = (cleaned.get("to_office") or "").strip()
        if not to_office:
            self.add_error("to_office", "To office is required.")
        return cleaned
