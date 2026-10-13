import hashlib
from datetime import timedelta
from django.contrib.auth import views
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from .models import LoginAttempt
from .access import audit


class LoginView(views.LoginView):
    def post(self, request, *args, **kwargs):
        keys = [hashlib.sha256(value.encode()).hexdigest() for value in [
            'ip:' + request.META.get('REMOTE_ADDR', ''),
            'user:' + request.POST.get('username', '').casefold()]]
        with transaction.atomic():
            attempts = []
            for key in sorted(keys):
                attempt, _ = LoginAttempt.objects.get_or_create(key=key)
                attempt = LoginAttempt.objects.select_for_update().get(pk=attempt.pk)
                if attempt.started < timezone.now() - timedelta(minutes=15):
                    attempt.started = timezone.now()
                    attempt.failures = 0
                if attempt.failures >= 10:
                    return HttpResponse('Too many login attempts. Try again in 15 minutes.', status=429)
                attempts.append(attempt)
            response = super().post(request, *args, **kwargs)
            for attempt in attempts:
                attempt.failures = 0 if response.status_code == 302 else attempt.failures + 1
                attempt.save()
            return response


class PasswordResetView(views.PasswordResetView):
    template_name = 'registration/password_reset.html'
    email_template_name = 'registration/password_reset_email.txt'
    subject_template_name = 'registration/password_reset_subject.txt'

    def form_valid(self, form):
        audit(self.request.user, 'password.reset.request', request=self.request)
        return super().form_valid(form)


class PasswordResetConfirmView(views.PasswordResetConfirmView):
    template_name = 'registration/password_reset_confirm.html'

    @transaction.atomic
    def form_valid(self, form):
        response = super().form_valid(form)
        audit(self.user, 'password.reset.email', self.user.pk, request=self.request)
        return response
