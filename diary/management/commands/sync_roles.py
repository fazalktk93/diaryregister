from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth.models import Group, Permission
from diary.access import audit


class Command(BaseCommand):
    help = 'Grant Movement to existing staff groups and Delete to Data Entry Operators.'

    @transaction.atomic
    def handle(self, *args, **options):
        permission = Permission.objects.get(content_type__app_label='diary', codename='add_diarymovement')
        groups = Group.objects.filter(name__in=['CDA admin', 'CDA operator'])
        for group in groups:
            group.permissions.add(permission)
        delete_permission = Permission.objects.get(content_type__app_label='diary', codename='delete_diary')
        for group in groups.filter(name='CDA operator'):
            group.permissions.add(delete_permission)
        audit(None, 'roles.register_permissions.granted', changes={'movement_groups': list(groups.values_list('name', flat=True)), 'delete_group': 'CDA operator', 'permissions_added': ['diary.add_diarymovement', 'diary.delete_diary']})
        self.stdout.write(self.style.SUCCESS('Movement granted to existing CDA admin/operator groups; Delete granted to CDA operator. No diary records or unrelated permissions were changed.'))
