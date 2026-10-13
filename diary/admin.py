"""Business mutations use the audited app; Django Admin is read-only."""
from django.contrib import admin
from django.contrib.auth.models import User, Group
from .access import membership_for
from .models import Diary, DiaryMovement, Office, Directorate, Membership, AuditLog, DirectorateSettings

for model in (User, Group):
    if admin.site.is_registered(model):
        admin.site.unregister(model)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        member = membership_for(request.user)
        return bool(member and (member.role == 'system' or member.directorate and member.directorate.is_active))

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        member = membership_for(request.user)
        if not member:
            return qs.none()
        if self.model == AuditLog and member.role == 'system':
            return qs.exclude(action__startswith='diary.')
        if self.model in (Directorate, Membership, DirectorateSettings) and member.role == 'system':
            return qs
        if not member.directorate_id or not member.directorate.is_active:
            return qs.none()
        if self.model == DiaryMovement:
            return qs.filter(diary__directorate_id=member.directorate_id)
        if self.model == Directorate:
            return qs.filter(pk=member.directorate_id)
        return qs.filter(directorate_id=member.directorate_id)


for model in (Diary, DiaryMovement, Office, Directorate, Membership, DirectorateSettings):
    admin.site.register(model, ReadOnlyAdmin)


@admin.register(AuditLog)
class AuditAdmin(ReadOnlyAdmin):
    list_display = ['timestamp', 'user', 'directorate', 'action', 'record_id']
    def has_view_permission(self, request, obj=None):
        member = membership_for(request.user)
        return bool(member and member.role in ('system', 'admin', 'auditor'))
