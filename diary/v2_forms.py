from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import Directorate, DirectorateSettings, Membership


class DirectorateForm(forms.ModelForm):
    class Meta:
        model = Directorate
        fields = ['name', 'code', 'is_active']


class SettingsForm(forms.ModelForm):
    class Meta:
        model = DirectorateSettings
        fields = ['report_title']


class AccountForm(forms.ModelForm):
    directorate = forms.ModelChoiceField(queryset=Directorate.objects.filter(is_active=True), required=False)
    role = forms.ChoiceField(choices=Membership.Role.choices)
    password = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active']

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        if actor.role != Membership.Role.SYSTEM:
            self.fields['role'].choices = [c for c in Membership.Role.choices if c[0] in ('operator', 'viewer', 'auditor')]
            self.fields['directorate'].queryset = Directorate.objects.filter(pk=actor.directorate_id)
            self.fields['directorate'].initial = actor.directorate_id
            self.fields['directorate'].disabled = True
        if self.instance.pk:
            membership = Membership.objects.filter(user=self.instance).first()
            if membership:
                self.fields['role'].initial = membership.role
                self.fields['directorate'].initial = membership.directorate_id

    def clean(self):
        values = super().clean()
        if values.get('role') != 'system' and not values.get('directorate'):
            self.add_error('directorate', 'Choose an active directorate.')
        password = values.get('password')
        if not self.instance.pk and not password:
            self.add_error('password', 'A password is required.')
        if password:
            candidate = get_user_model()(username=values.get('username'), email=values.get('email'), first_name=values.get('first_name'), last_name=values.get('last_name'))
            validate_password(password, candidate)
        return values
