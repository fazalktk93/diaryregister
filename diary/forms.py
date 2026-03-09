from __future__ import annotations

from django import forms
from django.utils import timezone
from django.utils.timezone import is_naive, make_aware

from .models import Diary, DiaryMovement


BOOTSTRAP_INPUT_CLASS = "form-control"
BOOTSTRAP_SELECT_CLASS = "form-select"


class DiaryCreateForm(forms.ModelForm):
    DIARY_TYPE_CHOICES = (
        ("file", "File"),
        ("file_service", "File + Service Book"),
        ("letter", "Letter"),
    )

    # Override diary_date to use timezone.localdate as default
    diary_date = forms.DateField(initial=timezone.localdate, required=True)

    # New 3-option type field that maps to file_letter and service_included
    diary_type = forms.ChoiceField(
        choices=DIARY_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": BOOTSTRAP_SELECT_CLASS}),
        required=True,
        initial="letter",
        label="Diary Type",
    )

    class Meta:
        model = Diary
        fields = [
            "diary_date",
            "received_diary_no",
            "received_from",
            "no_of_folders",
            "subject",
            "marked_to",
            "remarks",
        ]
        widgets = {
            "diary_date": forms.DateInput(attrs={"type": "date", "class": BOOTSTRAP_INPUT_CLASS}),
            "received_diary_no": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "placeholder": "e.g. REF-2026-001"}),
            "received_from": forms.TextInput(attrs={"class": BOOTSTRAP_INPUT_CLASS, "placeholder": "Office or sender name"}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing an existing diary, compute diary_type from file_letter and service_included
        if self.instance and self.instance.pk:
            file_letter = self.instance.file_letter or ""
            service_included = getattr(self.instance, "service_included", False)
            
            if file_letter == "File" and service_included:
                self.fields["diary_type"].initial = "file_service"
            elif file_letter == "File":
                self.fields["diary_type"].initial = "file"
            elif file_letter == "Letter":
                self.fields["diary_type"].initial = "letter"

    def clean(self):
        cleaned = super().clean()
        diary_type = (cleaned.get("diary_type") or "").strip()
        folders = cleaned.get("no_of_folders")
        
        # Map diary_type back to file_letter and service_included
        if diary_type == "file":
            cleaned["file_letter"] = "File"
            cleaned["service_included"] = False
            # For File, folders required and must be >= 1
            if folders in (None, ""):
                self.add_error("no_of_folders", "No. of folders is required for File.")
            else:
                try:
                    folders_int = int(folders)
                except (TypeError, ValueError):
                    self.add_error("no_of_folders", "Enter a valid number.")
                else:
                    if folders_int < 1:
                        self.add_error("no_of_folders", "Must be 1 or more for File.")
        
        elif diary_type == "file_service":
            cleaned["file_letter"] = "File"
            cleaned["service_included"] = True
            # For File + Service Book, folders required and must be >= 1
            if folders in (None, ""):
                self.add_error("no_of_folders", "No. of folders is required for File + Service Book.")
            else:
                try:
                    folders_int = int(folders)
                except (TypeError, ValueError):
                    self.add_error("no_of_folders", "Enter a valid number.")
                else:
                    if folders_int < 1:
                        self.add_error("no_of_folders", "Must be 1 or more for File + Service Book.")
        
        elif diary_type == "letter":
            cleaned["file_letter"] = "Letter"
            cleaned["service_included"] = False
            cleaned["no_of_folders"] = 0
        
        else:
            self.add_error("diary_type", "Please select a valid type.")

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
