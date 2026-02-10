from __future__ import annotations

from django import forms
from django.utils import timezone
from django.utils.timezone import is_naive, make_aware

from .models import Diary, DiaryMovement


BOOTSTRAP_INPUT_CLASS = "form-control"
BOOTSTRAP_SELECT_CLASS = "form-select"


class DiaryCreateForm(forms.ModelForm):
    FILE_LETTER_CHOICES = (
        ("File", "File"),
        ("Letter", "Letter"),
        ("Service Book", "Service Book"),
        ("Application", "Application"),
    )

    # Override diary_date to use timezone.localdate as default
    diary_date = forms.DateField(initial=timezone.localdate, required=True)

    # Dropdown (File / Letter)
    file_letter = forms.ChoiceField(
        choices=FILE_LETTER_CHOICES,
        widget=forms.Select(attrs={"class": BOOTSTRAP_SELECT_CLASS}),
        required=True,
        initial="Letter",
    )

    class Meta:
        model = Diary
        fields = [
            "diary_date",
            "received_diary_no",
            "received_from",
            "file_letter",
            "no_of_folders",
            "subject",
            "marked_to",
            "remarks",
        ]
        widgets = {
            "diary_date": forms.DateInput(attrs={"type": "date", "class": BOOTSTRAP_INPUT_CLASS}),
            "received_diary_no": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "placeholder": "e.g. REF-2026-001"}),
            "received_from": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "placeholder": "Office or sender name"}),
            "file_letter": forms.Select(attrs={"class": BOOTSTRAP_SELECT_CLASS}),
            "marked_to": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "placeholder": "Destination office"}),
            "no_of_folders": forms.NumberInput(attrs={"class": "form-control", "min": 0, "inputmode": "numeric"}),
            "subject": forms.Textarea(attrs={"class": BOOTSTRAP_INPUT_CLASS, "rows": 2, "placeholder": "Diary subject or description"}),
            "remarks": forms.Textarea(attrs={"class": BOOTSTRAP_INPUT_CLASS, "rows": 2, "placeholder": "Additional remarks (optional)"}),
        }

    # Make the field optional at the form level so disabled inputs (not submitted)
    # don't trigger a required-field error; clean() enforces when File is selected.
    no_of_folders = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0, "inputmode": "numeric"}),
    )

    def clean(self):
        cleaned = super().clean()
        kind = (cleaned.get("file_letter") or "").strip()
        folders = cleaned.get("no_of_folders")
        # For types that don't use folders, clear it
        if kind in ("Letter", "Application"):
            cleaned["no_of_folders"] = 0

        elif kind in ("File", "Service Book"):
            # For File and Service Book, folders required and must be >= 1
            if folders in (None, ""):
                self.add_error("no_of_folders", "No. of folders is required for File/Service Book.")
            else:
                try:
                    folders_int = int(folders)
                except (TypeError, ValueError):
                    self.add_error("no_of_folders", "Enter a valid number.")
                else:
                    if folders_int < 1:
                        self.add_error("no_of_folders", "Must be 1 or more for File/Service Book.")
        else:
            self.add_error("file_letter", "Please select a valid type.")

        return cleaned


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
        if is_naive(dt):
            return make_aware(dt, timezone.get_current_timezone())
        return dt

    def clean(self):
        cleaned = super().clean()
        to_office = (cleaned.get("to_office") or "").strip()
        if not to_office:
            self.add_error("to_office", "To office is required.")
        return cleaned
