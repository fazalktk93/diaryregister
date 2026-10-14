from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .access import audit
from django.db.models.signals import post_init, post_save, post_delete
from .models import Diary, Office
from .data_cache import invalidate_after_commit


@receiver(post_init, sender=Diary)
@receiver(post_init, sender=Office)
def remember_cache_directorate(sender, instance, **kwargs):
    instance._cache_original_directorate_id = instance.__dict__.get('directorate_id')


@receiver(post_save, sender=Diary)
@receiver(post_delete, sender=Diary)
@receiver(post_save, sender=Office)
@receiver(post_delete, sender=Office)
def invalidate_tenant_data(sender, instance, using, **kwargs):
    if sender is Diary and kwargs.get('update_fields') is not None and not set(kwargs['update_fields']) & {'directorate', 'directorate_id', 'year', 'diary_date', 'archived'}:
        return
    kind = 'dashboard' if sender is Diary else 'offices'
    invalidate_after_commit(kind,
        [instance.directorate_id, getattr(instance, '_cache_original_directorate_id', None)], using=using)
    instance._cache_original_directorate_id = instance.directorate_id


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
