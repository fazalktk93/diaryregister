from datetime import timedelta
from django.core.cache import caches
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from diary.data_cache import dashboard_summary, office_choices, generation_key
from diary.models import Directorate, Membership, Diary, Office
from .test_v2 import account


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], STATIC_ROOT=None,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'},
        'diary_data': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'isolated-cache-tests'}})
class DataCacheTests(TestCase):
    def setUp(self):
        caches['diary_data'].clear()
        self.a = Directorate.objects.create(name='Administration', code='ADM')
        self.b = Directorate.objects.create(name='Finance', code='FIN')
        self.operator = account('cache-operator', self.a)
        self.other = account('cache-finance', self.b)
        self.diary = Diary.create_with_next_number(created_by=self.operator, subject='ADM_CURRENT', marked_to='Office A')
        Diary.create_with_next_number(created_by=self.other, subject='FIN_CURRENT', marked_to='Office B')
        self.client.force_login(self.operator)

    def summary(self, directorate=None, year=None, today=None):
        directorate = directorate or self.a
        today = today or timezone.localdate()
        return dashboard_summary(Diary.objects.filter(directorate=directorate, archived=False),
            directorate.pk, year or today.year, today)

    def test_warm_dashboard_eliminates_summary_and_office_queries(self):
        self.client.get(reverse('dashboard'))
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 1)
        self.assertContains(response, 'ADM_CURRENT')
        self.assertNotContains(response, 'FIN_CURRENT')
        sql = [query['sql'].lower() for query in queries]
        self.assertFalse(any('count(' in query for query in sql))
        self.assertFalse(any('from "diary_office"' in query for query in sql))
        self.assertEqual(sum('from "diary_membership"' in query for query in sql), 1)

    def test_office_cache_is_scoped_and_reused(self):
        self.assertEqual(office_choices(self.a.pk), [{'name': 'Office A'}])
        with self.assertNumQueries(0):
            self.assertEqual(office_choices(self.a.pk), [{'name': 'Office A'}])
        self.assertEqual(office_choices(self.b.pk), [{'name': 'Office B'}])

    def test_committed_create_archive_and_delete_refresh_counts(self):
        self.assertEqual(self.summary()['total'], 1)
        with self.captureOnCommitCallbacks(execute=True):
            created = Diary.create_with_next_number(created_by=self.operator, subject='New')
        self.assertEqual(self.summary()['total'], 2)
        with self.captureOnCommitCallbacks(execute=True):
            created.archived = True
            created.save(update_fields=['archived'])
        self.assertEqual(self.summary()['total'], 1)
        with self.captureOnCommitCallbacks(execute=True):
            self.diary.delete()
        self.assertEqual(self.summary()['total'], 0)

    def test_committed_office_changes_refresh_choices(self):
        office_choices(self.a.pk)
        with self.captureOnCommitCallbacks(execute=True):
            office = Office.objects.create(directorate=self.a, name='New office')
        self.assertIn({'name': 'New office'}, office_choices(self.a.pk))
        with self.captureOnCommitCallbacks(execute=True):
            office.name = 'Renamed office'
            office.save()
        self.assertNotIn({'name': 'New office'}, office_choices(self.a.pk))
        self.assertIn({'name': 'Renamed office'}, office_choices(self.a.pk))
        with self.captureOnCommitCallbacks(execute=True):
            office.delete()
        self.assertEqual(office_choices(self.a.pk), [{'name': 'Office A'}])

    def test_reassignment_invalidates_both_directorates(self):
        office_choices(self.a.pk)
        office_choices(self.b.pk)
        with self.captureOnCommitCallbacks(execute=True):
            office = Office.objects.get(directorate=self.a, name='Office A')
            office.directorate = self.b
            office.save()
        self.assertEqual(office_choices(self.a.pk), [])
        self.assertIn({'name': 'Office A'}, office_choices(self.b.pk))

    def test_rollback_keeps_cache_valid(self):
        self.summary()
        key = generation_key('dashboard', self.a.pk)
        generation = caches['diary_data'].get(key)
        with self.assertRaises(ValueError):
            with transaction.atomic():
                self.diary.archived = True
                self.diary.save(update_fields=['archived'])
                raise ValueError('rollback')
        self.assertEqual(caches['diary_data'].get(key), generation)
        with self.assertNumQueries(0):
            self.assertEqual(self.summary()['total'], 1)

    def test_date_and_year_keys_keep_kpis_correct(self):
        today = timezone.localdate()
        self.assertEqual(self.summary(today=today)['today_count'], 1)
        self.assertEqual(self.summary(today=today + timedelta(days=1))['today_count'], 0)
        previous_year = self.summary(year=today.year - 1, today=today)
        self.assertEqual(previous_year['total'], 0)
        self.assertEqual(previous_year['today_count'], 1)

    def test_permissions_and_recent_records_stay_live(self):
        self.client.get(reverse('dashboard'))
        Diary.objects.filter(pk=self.diary.pk).update(subject='Changed without cached record')
        self.assertContains(self.client.get(reverse('dashboard')), 'Changed without cached record')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('dashboard')), 'FIN_CURRENT')
        self.b.is_active = False
        self.b.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 403)
