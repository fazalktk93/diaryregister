from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import Group, Permission
from diary.access import audit


class Command(BaseCommand):
    help = 'Keep Movement for admin/operators and restrict Delete to directorate admins.'

    @transaction.atomic
    def handle(self, *args, **options):
        permission = Permission.objects.get(content_type__app_label='diary', codename='add_diarymovement')
        groups = Group.objects.filter(name__in=['CDA admin', 'CDA operator'])
        delete_permission = Permission.objects.get(content_type__app_label='diary', codename='delete_diary')
        changes = []
        for group in groups.prefetch_related('permissions'):
            existing = {item.pk for item in group.permissions.all()}
            if permission.pk not in existing:
                group.permissions.add(permission)
                changes.append({'group': group.name, 'added': 'diary.add_diarymovement'})
            if group.name == 'CDA admin' and delete_permission.pk not in existing:
                group.permissions.add(delete_permission)
                changes.append({'group': group.name, 'added': 'diary.delete_diary'})
            elif group.name == 'CDA operator' and delete_permission.pk in existing:
                group.permissions.remove(delete_permission)
                changes.append({'group': group.name, 'removed': 'diary.delete_diary'})
        if changes:
            audit(None, 'roles.register_permissions.updated', changes={'changes': changes})
        self.stdout.write(self.style.SUCCESS('Movement remains available to admins/operators; Delete is restricted to directorate admins.'))
