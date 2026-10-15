from django import forms
from django.utils import timezone
from .models import DiaryMovement


class MovementForm(forms.ModelForm):
    class Meta:
        model = DiaryMovement
        fields = ['from_office', 'to_office', 'action_datetime', 'remarks']
        labels = {'to_office': 'To office', 'action_datetime': 'Movement date and time'}
        widgets = {'from_office': forms.TextInput(attrs={'class': 'form-control'}),
            'to_office': forms.TextInput(attrs={'class': 'form-control', 'list': 'office-suggestions', 'placeholder': 'Select or enter destination office'}),
            'action_datetime': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3})}

    def __init__(self, *args, diary, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['from_office'].disabled = True
        self.fields['from_office'].initial = diary.marked_to or diary.received_from
        self.fields['to_office'].required = True
        self.fields['action_datetime'].required = False
        self.fields['action_datetime'].initial = timezone.localtime()

    def clean_action_datetime(self):
        return self.cleaned_data.get('action_datetime') or timezone.now()


def role_group(role):
    from django.contrib.auth.models import Group, Permission
    group, _ = Group.objects.get_or_create(name='CDA ' + role)
    codes = ['view_diary'] if role != 'system' else []
    if role in ('admin', 'operator'):
        codes += ['add_diary', 'change_diary', 'add_diarymovement']
    if role == 'admin':
        codes += ['delete_diary']
    group.permissions.set(Permission.objects.filter(content_type__app_label='diary', codename__in=codes))
    return group
