from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .access import audit


@receiver(user_logged_in)
def logged_in(sender, request, user, **kwargs):
    audit(user, 'login.success', request=request)


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    audit(user, 'logout', request=request)


@receiver(user_login_failed)
def login_failed(sender, credentials, request, **kwargs):
    from django.contrib.auth import get_user_model
    from .models import Membership
    username = str(credentials.get('username', ''))[:150]
    user = get_user_model().objects.filter(username=username).first()
    member = Membership.objects.filter(user=user).first() if user else None
    audit(user, 'login.failed', changes={'attempted_username': username}, request=request,
        directorate=member.directorate if member else None)
