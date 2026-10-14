from copy import deepcopy
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TransactionTestCase, override_settings
from diary.legacy_import import import_source, prepare_source, legacy_roles
from diary.models import Diary, DiaryCounter, DiaryMovement, Directorate, Membership, AuditLog


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
        'diary_data': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'legacy-import-tests'}})
class LegacyImportTests(TransactionTestCase):
    def source(self):
        return {'auth_user': [{'id': 12, 'username': 'legacy-admin', 'password': make_password('Legacy-password!'),
            'is_superuser': 1, 'is_staff': 1, 'is_active': 1, 'date_joined': '2020-01-01 01:02:03',
            'last_login': None, 'first_name': '', 'last_name': '', 'email': ''},
            {'id': 27, 'username': 'legacy-clerk', 'password': make_password('Clerk-password!'),
            'is_superuser': 0, 'is_staff': 0, 'is_active': 1, 'date_joined': '2020-01-01 01:02:03',
            'last_login': None, 'first_name': '', 'last_name': '', 'email': ''}],
            'auth_group': [{'id': 1, 'name': 'dairyclerk'}], 'auth_user_groups': [{'id': 1, 'user_id': 27, 'group_id': 1}],
            'diary_diary': [{'id': 39, 'year': 2026, 'sequence': 75, 'diary_date': '2026-01-04',
                'created_at': '2026-01-04 03:04:05', 'created_by_id': 27, 'no_of_folders': 2,
                'file_letter': 'File', 'service_included': 1, 'subject': 'Historical subject',
                'marked_to': 'Office A', 'received_from': 'Sender', 'received_diary_no': 'REF-1',
                'remarks': '', 'marked_date': '2026-01-05', 'status': 'Forwarded'}],
            'diary_diarymovement': [{'id': 83, 'diary_id': 39, 'created_by_id': 12, 'year': 2026, 'sequence': 75,
                'from_office': 'Sender', 'to_office': 'Office A', 'action_type': 'Forwarded',
                'action_datetime': '2026-01-05 04:05:06', 'created_on': '2026-01-05 04:06:07', 'remarks': 'Old remarks'}],
            'diary_office': [{'id': 43, 'name': 'Office A'}], 'diary_appconfig': [], 'django_admin_log': [],
            'django_content_type': [], 'fingerprint': 'isolated-test-fingerprint'}

    def test_passwords_timestamps_relationships_and_next_number_are_preserved(self):
        rows = self.source()
        import_source(rows)
        self.assertEqual(Directorate.objects.count(), 1)
        self.assertEqual(Directorate.objects.get().name, 'Administration')
        self.assertEqual(Membership.objects.filter(directorate__code='ADM').count(), 2)
        user = get_user_model().objects.get(pk=27)
        self.assertTrue(user.check_password('Clerk-password!'))
        self.assertEqual(user.password, rows['auth_user'][1]['password'])
        self.assertEqual(user.membership.role, 'operator')
        self.assertTrue(user.has_perm('diary.add_diarymovement'))
        diary = Diary.objects.get(pk=39)
        self.assertEqual(diary.diary_no, '00075')
        self.assertEqual(diary.created_at.isoformat(), '2026-01-04T03:04:05+00:00')
        self.assertTrue(diary.service_included)
        movement = DiaryMovement.objects.get(pk=83)
        self.assertEqual(movement.created_by_id, 12)
        self.assertEqual(movement.created_on.isoformat(), '2026-01-05T04:06:07+00:00')
        self.assertEqual(DiaryCounter.objects.get(year=2026).value, 75)
        self.assertEqual(Diary.create_with_next_number(created_by=user).sequence, 76)
        self.assertTrue(AuditLog.objects.filter(action='legacy.sqlite.imported').exists())

    def test_repeat_import_is_refused_without_overwriting(self):
        rows = self.source()
        import_source(rows)
        with self.assertRaisesRegex(ValueError, 'Target contains'):
            import_source(rows)
        self.assertEqual(Diary.objects.count(), 1)

    def test_invalid_source_rolls_back_entire_import(self):
        rows = self.source()
        rows['diary_diarymovement'][0]['created_by_id'] = 999
        with self.assertRaisesRegex(ValueError, 'missing diary or user'):
            import_source(rows)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(Directorate.objects.exists())

    def test_duplicate_numbers_are_rejected(self):
        rows = self.source()
        duplicate = deepcopy(rows['diary_diary'][0])
        duplicate['id'] = 99
        rows['diary_diary'].append(duplicate)
        with self.assertRaisesRegex(ValueError, 'duplicate numbering'):
            prepare_source(rows)

    def test_admin_membership_takes_precedence_over_legacy_clerk_group(self):
        rows = self.source()
        rows['auth_group'].append({'id': 2, 'name': 'admin'})
        rows['auth_user_groups'].append({'id': 2, 'user_id': 27, 'group_id': 2})
        self.assertEqual(legacy_roles(rows)[27], 'admin')
