"""Validated, one-time import of the original single-workspace SQLite schema."""
import hashlib
import sqlite3
from collections import Counter
from contextlib import contextmanager
from datetime import timezone as datetime_timezone
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.color import no_style
from django.db import connection, transaction
from django.utils.dateparse import parse_date, parse_datetime
from .models import AppConfig, AuditLog, Diary, DiaryCounter, DiaryMovement, Directorate, DirectorateSettings, Membership, Office
from .movement_forms import role_group
from .data_cache import invalidate_after_commit


TABLES = ('auth_user', 'auth_group', 'auth_user_groups', 'diary_diary',
    'diary_diarymovement', 'diary_office', 'diary_appconfig', 'django_admin_log', 'django_content_type')


def read_source(path):
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        source.execute('PRAGMA query_only=ON')
        source.execute('BEGIN')
        if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed.')
        if source.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite has broken foreign-key references.')
        existing = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'auth_user', 'diary_diary', 'diary_diarymovement', 'diary_office'}
        if required - existing:
            raise ValueError('This file is missing required diary-register tables.')
        if existing & {'diary_membership', 'diary_directorate'}:
            raise ValueError('This importer expects the original single-workspace schema, not a v2 database.')
        models = {'auth_user': get_user_model(), 'diary_diary': Diary, 'diary_diarymovement': DiaryMovement, 'diary_office': Office}
        for table, model in models.items():
            columns = {row[1] for row in source.execute(f'PRAGMA table_info("{table}")')}
            expected = {field.attname for field in model._meta.concrete_fields} - {'directorate_id', 'archived'}
            if expected - columns:
                raise ValueError(f'{table} is missing required historical columns: {", ".join(sorted(expected - columns))}.')
        rows = {table: [dict(row) for row in source.execute(f'SELECT * FROM "{table}" ORDER BY id')]
            if table in existing else [] for table in TABLES}
    rows['fingerprint'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return rows


def legacy_roles(rows):
    groups = {row['id']: row['name'].casefold() for row in rows['auth_group']}
    assignments = {}
    for row in rows['auth_user_groups']:
        assignments.setdefault(row['user_id'], set()).add(groups[row['group_id']])
    roles = {}
    for user in rows['auth_user']:
        names = assignments.get(user['id'], set())
        if user['is_superuser'] or user['is_staff'] or names & {'admin', 'cda admin'}:
            role = 'admin'
        elif names & {'dairyclerk', 'diaryclerk', 'operator', 'cda operator'}:
            role = 'operator'
        else:
            role = 'viewer'
        roles[user['id']] = role
    return roles


def source_summary(rows):
    years = {}
    for row in rows['diary_diary']:
        years[row['year']] = max(years.get(row['year'], 0), row['sequence'])
    return {'workspace': 'Administration Directorate', 'users': len(rows['auth_user']),
        'diaries': len(rows['diary_diary']), 'movements': len(rows['diary_diarymovement']),
        'offices': len(rows['diary_office']), 'legacy_admin_logs': len(rows['django_admin_log']),
        'roles': dict(Counter(legacy_roles(rows).values())), 'year_counters': years}


def objects_from_rows(model, rows):
    result = []
    fields = {field.attname: field for field in model._meta.concrete_fields}
    for row in rows:
        values = {}
        for name, field in fields.items():
            if name not in row:
                continue
            value = row[name]
            kind = field.get_internal_type()
            if kind == 'DateTimeField' and value is not None:
                value = parse_datetime(str(value))
                if value is None:
                    raise ValueError(f'{model._meta.db_table} row {row["id"]}: invalid {name}.')
                if value.tzinfo is None:
                    # Legacy Django SQLite timestamps are UTC when USE_TZ=True.
                    value = value.replace(tzinfo=datetime_timezone.utc)
            elif kind == 'DateField' and value is not None:
                value = parse_date(str(value))
                if value is None:
                    raise ValueError(f'{model._meta.db_table} row {row["id"]}: invalid {name}.')
            elif kind == 'BooleanField':
                if value not in (0, 1, False, True):
                    raise ValueError(f'{model._meta.db_table} row {row["id"]}: invalid {name}.')
                value = bool(value)
            if isinstance(value, str) and ('\x00' in value or (field.max_length and len(value) > field.max_length)):
                raise ValueError(f'{model._meta.db_table} row {row["id"]}: invalid length or NUL in {name}.')
            if value is None and not field.null:
                raise ValueError(f'{model._meta.db_table} row {row["id"]}: missing {name}.')
            values[name] = value
        result.append(model(**values))
    return result


def prepare_source(rows):
    users = objects_from_rows(get_user_model(), rows['auth_user'])
    diaries = objects_from_rows(Diary, rows['diary_diary'])
    movements = objects_from_rows(DiaryMovement, rows['diary_diarymovement'])
    offices = objects_from_rows(Office, rows['diary_office'])
    configs = objects_from_rows(AppConfig, rows['diary_appconfig'])
    if not users:
        raise ValueError('No legacy users found.')
    user_ids = {user.pk for user in users}
    if len({user.username for user in users}) != len(users):
        raise ValueError('Duplicate usernames found.')
    numbers = set()
    diary_ids = {diary.pk: diary for diary in diaries}
    for diary in diaries:
        number = (diary.year, diary.sequence)
        if number in numbers or not 1 <= diary.year <= 9999 or diary.sequence < 1 or diary.no_of_folders < 0:
            raise ValueError(f'Diary {diary.pk} has invalid or duplicate numbering/folder count.')
        numbers.add(number)
        if diary.created_by_id not in user_ids:
            raise ValueError(f'Diary {diary.pk} references a missing user.')
    for movement in movements:
        diary = diary_ids.get(movement.diary_id)
        if diary is None or movement.created_by_id not in user_ids:
            raise ValueError(f'Movement {movement.pk} references a missing diary or user.')
        if (movement.year, movement.sequence) != (diary.year, diary.sequence):
            raise ValueError(f'Movement {movement.pk} numbering does not match its diary.')
    if len({office.name for office in offices}) != len(offices):
        raise ValueError('Duplicate office names found.')
    if len(configs) > 1:
        raise ValueError('Multiple legacy application configurations found.')
    for row in rows['django_admin_log']:
        if row['user_id'] not in user_ids or parse_datetime(row['action_time']) is None:
            raise ValueError(f'Admin log {row["id"]} has an invalid user or timestamp.')
    return users, diaries, movements, offices, configs


@contextmanager
def original_timestamps(model):
    # Run in the dedicated import process; prevent auto_now from rewriting history.
    fields = [(field, field.auto_now, field.auto_now_add) for field in model._meta.fields
        if hasattr(field, 'auto_now')]
    try:
        for field, _, _ in fields:
            field.auto_now = field.auto_now_add = False
        yield
    finally:
        for field, auto_now, auto_now_add in fields:
            field.auto_now, field.auto_now_add = auto_now, auto_now_add


def require_empty_target():
    for model in (get_user_model(), Directorate, Membership, Diary, DiaryMovement, Office,
                  DiaryCounter, DirectorateSettings, AppConfig, AuditLog):
        if model.objects.exists():
            raise ValueError('Target contains app data. Use a separate empty PostgreSQL database; nothing was overwritten.')


@transaction.atomic
def import_source(rows, prepared=None):
    require_empty_target()
    users, diaries, movements, offices, configs = prepared or prepare_source(rows)
    directorate = Directorate.objects.create(name='Administration', code='ADM')
    DirectorateSettings.objects.create(directorate=directorate, report_title='Administration Directorate')
    roles = legacy_roles(rows)
    get_user_model().objects.bulk_create(users, batch_size=500)
    Membership.objects.bulk_create([Membership(user_id=user.pk, directorate=directorate, role=roles[user.pk]) for user in users])
    through = get_user_model().groups.through
    groups = {role: role_group(role) for role in set(roles.values())}
    through.objects.bulk_create([through(user_id=user.pk, group_id=groups[roles[user.pk]].pk) for user in users])
    for model, items in ((Office, offices), (Diary, diaries), (DiaryMovement, movements), (AppConfig, configs)):
        if model in (Office, Diary):
            for item in items:
                item.directorate_id = directorate.pk
        with original_timestamps(model):
            model.objects.bulk_create(items, batch_size=500)
    summary = source_summary(rows)
    DiaryCounter.objects.bulk_create([DiaryCounter(directorate=directorate, year=year, value=maximum)
        for year, maximum in summary['year_counters'].items()])
    content_types = {row['id']: f'{row["app_label"]}.{row["model"]}' for row in rows['django_content_type']}
    logs = []
    for row in rows['django_admin_log']:
        timestamp = parse_datetime(row['action_time'])
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=datetime_timezone.utc)
        logs.append(AuditLog(user_id=row['user_id'], directorate=directorate, action='legacy.admin.change',
            record_id=str(row['object_id'] or '')[:64], timestamp=timestamp,
            changes={'model': content_types.get(row['content_type_id'], 'unknown'),
                'object_repr': row['object_repr'], 'change_message': row['change_message'], 'action_flag': row['action_flag']}))
    with original_timestamps(AuditLog):
        AuditLog.objects.bulk_create(logs, batch_size=500)
    AuditLog.objects.create(directorate=directorate, action='legacy.sqlite.imported',
        changes={**summary, 'source_sha256': rows['fingerprint']})
    for model, expected in ((get_user_model(), len(users)), (Diary, len(diaries)),
                            (DiaryMovement, len(movements)), (Office, len(offices))):
        if model.objects.count() != expected:
            raise ValueError('Imported count verification failed; transaction rolled back.')
    with connection.cursor() as cursor:
        for sql in connection.ops.sequence_reset_sql(no_style(),
                [get_user_model(), Office, Diary, DiaryMovement, AppConfig, AuditLog]):
            cursor.execute(sql)
    invalidate_after_commit('dashboard', [directorate.pk])
    invalidate_after_commit('offices', [directorate.pk])
    return summary
