from django import forms
from django.utils import timezone
from .models import Diary, DiaryMovement


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

    diary_date = forms.DateField(initial=timezone.localdate)


class MovementCreateForm(forms.ModelForm):
    class Meta:
        model = DiaryMovement
        fields = ["from_office", "to_office", "action_type", "action_datetime", "remarks"]
        widgets = {
            "action_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def clean_action_type(self):
        v = (self.cleaned_data.get("action_type") or "").strip()
        if not v:
            raise forms.ValidationError("ActionType is required.")
        return v
