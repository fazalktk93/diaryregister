from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from .models import Membership, Diary, AuditLog


def membership_for(user):
    if not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.select_related('directorate').filter(user=user).first()


def scoped_diaries(user):
    membership = membership_for(user)
    if not membership or not membership.directorate_id or not membership.directorate.is_active:
        raise PermissionDenied('An active directorate is required.')
    return Diary.objects.filter(directorate_id=membership.directorate_id, archived=False)


def require_roles(*roles):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            membership = membership_for(request.user)
            if not membership or membership.role not in roles:
                raise PermissionDenied
            if membership.role != Membership.Role.SYSTEM and (not membership.directorate_id or not membership.directorate.is_active):
                raise PermissionDenied
            request.membership = membership
            permissions = {'diary_create': 'add_diary', 'diary_edit': 'change_diary', 'diary_delete': 'delete_diary', 'movement_add': 'add_diarymovement'}
            if view.__name__ in permissions and not request.user.has_perm('diary.' + permissions[view.__name__]):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def audit(user, action, record_id='', changes=None, request=None, directorate=None):
    import ipaddress
    membership = membership_for(user) if user else None
    ip = request.META.get('REMOTE_ADDR') if request else None
    try:
        ip = str(ipaddress.ip_address(ip)) if ip else None
    except ValueError:
        ip = None
    return AuditLog.objects.create(user=user if user and user.is_authenticated else None,
        directorate=directorate or (membership.directorate if membership else None),
        action=action, record_id=str(record_id), changes=changes or {}, ip=ip)


def branding(request):
    membership = membership_for(request.user)
    route = request.resolver_match.url_name if request.resolver_match else ''
    page_titles = {'dashboard': 'Overview', 'diary_list': 'Diary register', 'reports_table': 'Reports',
        'diary_year_report': 'Yearly report', 'diary_create': 'Register diary', 'diary_edit': 'Edit diary',
        'diary_detail': 'Diary details', 'users': 'User management', 'user_create': 'Create user',
        'user_edit': 'Edit user', 'user_password': 'Reset password', 'directorates': 'Directorates',
        'directorate_create': 'New directorate', 'directorate_edit': 'Edit directorate',
        'directorate_settings': 'Directorate settings', 'audit_logs': 'Audit log', 'directory': 'Office directory',
        'change_password': 'Change password'}
    return {'account_membership': membership, 'current_directorate': membership.directorate if membership else None,
            'workspace_page_title': page_titles.get(route, 'Diary register'), 'active_route': route,
            'can_write': bool(membership and membership.role in ('admin', 'operator')),
            'can_edit': bool(membership and membership.role in ('admin', 'operator') and request.user.has_perm('diary.change_diary')),
            'can_move': bool(membership and membership.role in ('admin', 'operator') and request.user.has_perm('diary.add_diarymovement')),
            'can_delete': bool(membership and membership.role in ('admin', 'operator') and request.user.has_perm('diary.delete_diary')),
            'can_manage': bool(membership and membership.role in ('system', 'admin'))}
