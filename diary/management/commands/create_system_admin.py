import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from diary.models import Membership
from diary.access import audit
from diary.v2_views import assign_role_permissions


class Command(BaseCommand):
    help = 'Create the first system administrator, without implicit diary access.'

    @transaction.atomic
    def handle(self, *args, **options):
        if Membership.objects.filter(role='system', user__is_active=True).exists():
            raise CommandError('A system administrator already exists. Use the user-management interface.')
        username = input('System administrator username: ').strip()
        email = input('Email (optional): ').strip()
        password = getpass.getpass('Password (hidden): ')
        if password != getpass.getpass('Confirm password: '):
            raise CommandError('Passwords did not match.')
        user = get_user_model()(username=username, email=email)
        try:
            validate_password(password, user)
            user.full_clean(exclude=['password'])
        except ValidationError as error:
            raise CommandError('; '.join(error.messages))
        user.set_password(password)
        user.save()
        Membership.objects.create(user=user, role='system')
        assign_role_permissions(user)
        audit(user, 'user.created.bootstrap', user.pk)
        self.stdout.write(self.style.SUCCESS('System administrator created. Sign in at /login/ and create directorates and their users.'))
