import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from diary.access import scoped_diaries
from diary.models import Directorate, DirectorateSettings, Membership, Diary, DiaryCounter, AuditLog
from diary.v2_views import assign_role_permissions


def account(username, directorate=None, role='operator'):
    user = get_user_model().objects.create_user(username=username, password='S3cure-Office-Password!')
    Membership.objects.create(user=user, directorate=directorate, role=role)
    assign_role_permissions(user)
    return user


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], STATIC_ROOT=None)
class IsolationTests(TestCase):
    def setUp(self):
        self.a = Directorate.objects.create(name='Administration', code='ADM')
        self.b = Directorate.objects.create(name='Finance', code='FIN')
        self.operator = account('operator', self.a)
        self.other = account('finance', self.b)
        self.admin = account('admin', self.a, 'admin')
        self.viewer = account('viewer', self.a, 'viewer')
        self.auditor = account('auditor', self.a, 'auditor')
        self.system = account('system', role='system')
        self.diary = Diary.create_with_next_number(created_by=self.operator, subject='ADM_VISIBLE', marked_to='Office A')
        self.foreign = Diary.create_with_next_number(created_by=self.other, subject='FIN_SECRET', marked_to='Office B')
        self.client.force_login(self.operator)

    def data(self, **extra):
        result = {'diary_date': str(timezone.localdate()), 'diary_type': 'letter', 'marked_to': 'Destination', 'subject': 'Registered safely', 'directorate': self.b.pk}
        result.update(extra)
        return result

    def test_register_avoids_duplicate_counts_and_unused_movement_queries(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('diary_list'))
        self.assertEqual(response.status_code, 200)
        selects = [query['sql'].lower() for query in queries if query['sql'].lstrip().lower().startswith('select')]
        self.assertEqual(sum('from "diary_membership"' in sql for sql in selects), 1)
        self.assertEqual(sum('count(' in sql and 'from "diary_diary"' in sql for sql in selects), 1)
        self.assertFalse(any('from "diary_diarymovement"' in sql for sql in selects))

    def test_dashboard_combines_kpis_without_changing_counts(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 1)
        self.assertEqual(response.context['today_count'], 1)
        self.assertEqual(response.context['month_count'], 1)
        selects = [query['sql'].lower() for query in queries if query['sql'].lstrip().lower().startswith('select')]
        self.assertEqual(sum('from "diary_membership"' in sql for sql in selects), 1)
        self.assertEqual(sum('today_count' in sql and 'month_count' in sql for sql in selects), 1)

    def test_cached_membership_does_not_survive_request(self):
        self.assertEqual(self.client.get(reverse('diary_list')).status_code, 200)
        Membership.objects.filter(user=self.operator).update(directorate=self.b)
        response = self.client.get(reverse('diary_list'))
        self.assertContains(response, 'FIN_SECRET')
        self.assertNotContains(response, 'ADM_VISIBLE')
        self.b.is_active = False
        self.b.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(reverse('diary_list')).status_code, 403)

    def test_independent_five_digit_numbering(self):
        self.assertEqual(self.diary.diary_no, '00001')
        self.assertEqual(self.foreign.diary_no, '00001')
        next_diary = Diary.create_with_next_number(created_by=self.operator)
        self.assertEqual(next_diary.diary_no, '00002')

    def test_new_year_and_official_timezone(self):
        with patch('diary.models.timezone.localdate', return_value=date(2030, 1, 1)):
            diary = Diary.create_with_next_number(created_by=self.operator, year=1999)
        self.assertEqual(diary.year, 2030)
        self.assertEqual(diary.diary_no, '00001')
        self.diary.refresh_from_db()
        self.assertEqual(self.diary.diary_no, '00001')
        with timezone.override('Asia/Karachi'):
            instant = datetime(2029, 12, 31, 20, tzinfo=ZoneInfo('UTC'))
            self.assertEqual(timezone.localdate(instant), date(2030, 1, 1))

    def test_unique_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Diary.objects.create(directorate=self.a, created_by=self.operator, year=self.diary.year, sequence=1)

    def test_create_ignores_forged_tenant_and_audits(self):
        response = self.client.post(reverse('diary_create'), self.data())
        self.assertEqual(response.status_code, 302)
        diary = Diary.objects.get(subject='Registered safely')
        self.assertEqual(diary.directorate_id, self.a.pk)
        self.assertTrue(AuditLog.objects.filter(action='diary.created', record_id=str(diary.pk), directorate=self.a).exists())
        self.assertEqual(diary.movements.count(), 1)

    def test_create_audit_failure_rolls_back_diary_and_counter(self):
        before = DiaryCounter.objects.get(directorate=self.a, year=self.diary.year).value
        with patch('diary.v2_views.audit', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('diary_create'), self.data())
        self.assertFalse(Diary.objects.filter(subject='Registered safely').exists())
        self.assertEqual(DiaryCounter.objects.get(directorate=self.a, year=self.diary.year).value, before)

    def test_detail_and_edit_foreign_record_return_404(self):
        for route in ['diary_detail', 'diary_edit']:
            self.assertEqual(self.client.get(reverse(route, args=[self.foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('diary_edit', args=[self.foreign.pk]), self.data()).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertEqual(self.foreign.subject, 'FIN_SECRET')

    def test_archive_foreign_record_return_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('diary_delete', args=[self.foreign.pk])).status_code, 404)
        self.foreign.refresh_from_db()
        self.assertFalse(self.foreign.archived)

    def test_archive_preserves_number_and_audits(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('diary_delete', args=[self.diary.pk]))
        self.assertEqual(response.status_code, 302)
        self.diary.refresh_from_db()
        self.assertTrue(self.diary.archived)
        self.assertEqual(self.diary.diary_no, '00001')
        self.assertEqual(scoped_diaries(self.admin).count(), 0)
        self.assertTrue(AuditLog.objects.filter(action='diary.archived').exists())
        self.assertEqual(Diary.create_with_next_number(created_by=self.operator).diary_no, '00002')

    def test_archive_requires_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('diary_delete', args=[self.diary.pk])).status_code, 405)

    def test_viewer_cannot_write_or_manage(self):
        self.client.force_login(self.viewer)
        for url in [reverse('diary_create'), reverse('diary_edit', args=[self.diary.pk]), reverse('users')]:
            self.assertEqual(self.client.post(url, self.data()).status_code, 403)
        self.assertEqual(self.client.get(reverse('diary_list')).status_code, 200)

    def test_django_permission_required_for_writes(self):
        self.operator.groups.clear()
        self.assertEqual(self.client.post(reverse('diary_create'), self.data()).status_code, 403)

    def test_search_and_all_report_pages_are_isolated(self):
        for url in [reverse('diary_list'), reverse('reports_table'), reverse('diary_year_report', args=[self.diary.year])]:
            response = self.client.get(url)
            self.assertContains(response, 'ADM_VISIBLE')
            self.assertNotContains(response, 'FIN_SECRET')
        response = self.client.get(reverse('diary_list'), {'q': 'FIN_SECRET'})
        self.assertEqual(response.context['total'], 0)

    def test_column_filters_and_exports_use_identical_scope(self):
        response = self.client.get(reverse('diary_list'), {'subject': 'FIN_SECRET'})
        self.assertEqual(response.context['total'], 0)
        response = self.client.get(reverse('report_csv'), {'subject': 'FIN_SECRET'})
        self.assertNotContains(response, 'FIN_SECRET')
        self.assertNotContains(response, 'ADM_VISIBLE')
        response = self.client.get(reverse('diary_list'), {'subject': 'ADM_VISIBLE', 'no_of_folders': 0})
        self.assertEqual(response.context['total'], 1)
        self.assertEqual(self.client.get(reverse('diary_list'), {'no_of_folders': -1}).status_code, 400)

    def test_number_format_boundaries(self):
        from diary.models import format_diary_number
        self.assertEqual(format_diary_number(9), '00009')
        self.assertEqual(format_diary_number(99999), '99999')

    def test_login_page_has_no_workspace_or_admin_identity(self):
        self.client.logout()
        response = self.client.get(reverse('login'))
        self.assertNotContains(response, 'id="navigation"')
        self.assertNotContains(response, 'System administration')
        self.assertNotContains(response, 'System Administrator')
        self.assertContains(response, 'Welcome back')

    def test_modal_diary_form_and_validation_preserve_inputs(self):
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        response = self.client.get(reverse('diary_create'), **headers)
        self.assertContains(response, 'data-modal-form')
        self.assertNotContains(response, '<html')
        response = self.client.post(reverse('diary_create'), self.data(marked_to=''), **headers)
        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()['success'])
        self.assertIn('Registered safely', response.json()['html'])
        self.assertIn('destination', response.json()['html'])
        response = self.client.post(reverse('diary_create'), self.data(), **headers)
        self.assertEqual(response.json(), {'success': True})
        self.assertEqual(Diary.objects.get(subject='Registered safely').directorate_id, self.a.pk)

    def test_modal_requests_cannot_bypass_role_or_tenant(self):
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        self.assertEqual(self.client.get(reverse('diary_edit', args=[self.foreign.pk]), **headers).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('diary_create'), **headers).status_code, 403)

    def test_modal_user_creation_remains_scoped(self):
        self.client.force_login(self.admin)
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        response = self.client.get(reverse('user_create'), **headers)
        self.assertContains(response, 'data-modal-form')
        response = self.client.post(reverse('user_create'), {'username': 'modaluser', 'role': 'operator', 'directorate': self.b.pk, 'password': 'A-Strong-Password-938!', 'is_active': True}, **headers)
        self.assertEqual(response.json(), {'success': True})
        self.assertEqual(get_user_model().objects.get(username='modaluser').membership.directorate_id, self.a.pk)

    def test_csv_isolation_number_and_formula_escaping(self):
        self.diary.subject = '=HYPERLINK("evil")'
        self.diary.save()
        response = self.client.get(reverse('reports_csv', args=[self.diary.year]))
        self.assertContains(response, '00001')
        self.assertNotContains(response, 'FIN_SECRET')
        self.assertContains(response, "'=HYPERLINK")

    def test_pdf_actual_number_and_isolation(self):
        # Inspect the actual PDF construction, not a separate output helper.
        with patch('diary.v2_views.SimpleDocTemplate.build') as build:
            response = self.client.get(reverse('reports_pdf', args=[self.diary.year]))
        self.assertEqual(response.status_code, 200)
        table = build.call_args.args[0][-1]
        content = ' '.join(cell.getPlainText() for row in table._cellvalues for cell in row)
        self.assertIn('00001', content)
        self.assertIn('ADM_VISIBLE', content)
        self.assertNotIn('FIN_SECRET', content)
        self.assertNotIn(f'{self.diary.year}-00001', content)

    def test_pdf_escapes_user_markup(self):
        self.diary.subject = '<img src="http://invalid/secret"/> & text'
        self.diary.save()
        response = self.client.get(reverse('reports_pdf', args=[self.diary.year]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF-'))

    def test_exports_require_login(self):
        self.client.logout()
        for route in ['reports_csv', 'reports_pdf']:
            self.assertEqual(self.client.get(reverse(route, args=[self.diary.year])).status_code, 302)

    def test_month_year_dashboard_links_and_counts(self):
        registered = datetime(2026, 3, 15, 10, tzinfo=ZoneInfo('Asia/Karachi'))
        Diary.objects.filter(pk=self.diary.pk).update(year=2026, created_at=registered, diary_date=date(2026, 3, 15))
        Diary.objects.filter(pk=self.foreign.pk).update(year=2026, created_at=registered, diary_date=date(2026, 3, 15))
        response = self.client.get(reverse('dashboard'), {'year': 2026})
        self.assertEqual(response.context['total'], 1)
        self.assertEqual(response.context['months'][2]['count'], 1)
        self.assertContains(response, '/list/?year=2026&month=3')
        self.assertContains(response, '/list/?year=2026')
        self.assertEqual(list(response.context['years'])[0]['count'], 1)
        march = self.client.get(reverse('diary_list'), {'year': 2026, 'month': 3})
        april = self.client.get(reverse('diary_list'), {'year': 2026, 'month': 4})
        self.assertEqual(march.context['total'], 1)
        self.assertEqual(april.context['total'], 0)
        yearly = self.client.get(reverse('diary_list'), {'year': 2026})
        self.assertEqual(yearly.context['total'], 1)

    def test_month_filters_follow_displayed_diary_date(self):
        registered = datetime(2026, 10, 1, 0, 30, tzinfo=ZoneInfo('Asia/Karachi'))
        Diary.objects.filter(pk=self.diary.pk).update(year=2026, created_at=registered, diary_date=date(2026, 3, 1))
        response = self.client.get(reverse('diary_list'), {'year': 2026, 'month': 3, 'date_from': '2026-03-01', 'date_to': '2026-03-01'})
        self.assertEqual(response.context['total'], 1)

    def test_creation_date_is_today_and_edit_preserves_existing_date(self):
        self.client.post(reverse('diary_create'), self.data(diary_date='1999-01-01'))
        diary = Diary.objects.get(subject='Registered safely')
        self.assertEqual(diary.diary_date, timezone.localdate())
        Diary.objects.filter(pk=diary.pk).update(diary_date=date(2020, 6, 1))
        response = self.client.post(reverse('diary_edit', args=[diary.pk]), self.data(diary_date='2030-01-01', subject='Edited safely'))
        self.assertEqual(response.status_code, 302)
        diary.refresh_from_db()
        self.assertEqual(diary.diary_date, date(2020, 6, 1))

    def test_office_picker_only_contains_own_directorate_offices(self):
        response = self.client.get(reverse('diary_create'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(response, 'Show saved offices')
        self.assertContains(response, 'Office A')
        self.assertNotContains(response, 'Office B')

    def test_register_and_reports_have_different_actions(self):
        register = self.client.get(reverse('diary_list'))
        reports = self.client.get(reverse('reports_table'))
        self.assertContains(register, 'Add diary')
        self.assertContains(register, '>Reports</a>')
        self.assertContains(reports, 'Generate report')
        self.assertContains(reports, 'PDF report')
        self.assertNotContains(reports, 'data-modal-title="Edit diary')

    def test_month_and_today_kpis_link_to_exact_filter(self):
        today = timezone.localdate()
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, f'/list/?year={today.year}&month={today.month}')
        self.assertContains(response, f'/list/?date_from={today.isoformat()}&date_to={today.isoformat()}')
        monthly = self.client.get(reverse('diary_list'), {'year': today.year, 'month': today.month})
        daily = self.client.get(reverse('diary_list'), {'date_from': today.isoformat(), 'date_to': today.isoformat()})
        self.assertEqual(monthly.context['total'], response.context['month_count'])
        self.assertEqual(daily.context['total'], response.context['today_count'])

    def test_pdf_preserves_original_register_columns_and_widths(self):
        with patch('diary.v2_views.SimpleDocTemplate.build') as build:
            self.client.get(reverse('reports_pdf', args=[self.diary.year]))
        table = build.call_args.args[0][-1]
        self.assertEqual([cell.getPlainText() for cell in table._cellvalues[0]], ['Diary No', 'Date', 'Rcvd No', 'Rcvd From', 'File/Letter', 'Folders', 'Subject', 'Movement'])
        self.assertEqual(table._colWidths, [60, 50, 45, 80, 60, 40, 240, 320])
        logo = build.call_args.args[0][0]._cellvalues[0][0]
        self.assertEqual(logo.drawWidth, 80)
        self.assertAlmostEqual(logo.drawHeight / logo.drawWidth, logo.imageHeight / logo.imageWidth)

    def test_pdf_heading_uses_full_directorate_name(self):
        for name, expected in [('Administration', 'Administration Directorate'), ('Finance', 'Finance Directorate'), ('Finance Directorate', 'Finance Directorate')]:
            self.a.name = name
            self.a.save()
            with patch('diary.v2_views.SimpleDocTemplate.build') as build:
                self.client.get(reverse('reports_pdf', args=[self.diary.year]))
            heading = build.call_args.args[0][0]._cellvalues[0][1].getPlainText()
            self.assertIn('Diary Record of ' + expected, heading)
            self.assertNotIn('Directorate Directorate', heading)

    def test_pdf_order_is_ascending_but_register_remains_newest_first(self):
        second = Diary.create_with_next_number(created_by=self.operator, subject='Second diary')
        with patch('diary.v2_views.SimpleDocTemplate.build') as build:
            self.client.get(reverse('reports_pdf', args=[self.diary.year]))
        rows = build.call_args.args[0][-1]._cellvalues
        self.assertEqual([row[0].getPlainText() for row in rows[1:]], ['00001', '00002'])
        register = self.client.get(reverse('diary_list'))
        self.assertEqual([entry.pk for entry in register.context['page_obj']], [second.pk, self.diary.pk])

    def test_detail_history_is_visible_with_header_actions(self):
        self.client.post(reverse('movement_add', args=[self.diary.pk]), {'to_office': 'History destination', 'remarks': 'Visible history remark'})
        response = self.client.get(reverse('diary_detail', args=[self.diary.pk]))
        self.assertContains(response, 'id="movement-history-title"')
        self.assertContains(response, 'History destination')
        self.assertContains(response, 'Visible history remark')
        self.assertContains(response, 'aria-label="Diary actions"')
        self.assertContains(response, 'data-modal-title="Movement')
        self.assertContains(response, 'data-modal-title="Edit diary')
        self.assertContains(response, 'data-bs-target="#deleteDiaryModal"')
        self.assertNotContains(response, '<details')

    def test_register_uses_original_movement_action(self):
        response = self.client.get(reverse('diary_list'))
        self.assertContains(response, 'data-modal-title="Movement')
        self.assertNotContains(response, 'data-modal-title="Edit diary')
        self.assertContains(response, '>View</a>')

    def test_operator_can_edit_move_and_delete_own_diary(self):
        self.assertTrue(self.operator.has_perm('diary.change_diary'))
        self.assertTrue(self.operator.has_perm('diary.add_diarymovement'))
        self.assertTrue(self.operator.has_perm('diary.delete_diary'))
        detail = self.client.get(reverse('diary_detail', args=[self.diary.pk]))
        self.assertContains(detail, 'Edit diary')
        self.assertContains(detail, 'Delete diary')
        self.assertEqual(self.client.post(reverse('diary_delete', args=[self.foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('diary_delete', args=[self.diary.pk])).status_code, 302)
        self.diary.refresh_from_db()
        self.assertTrue(self.diary.archived)

    def test_movement_is_scoped_audited_and_updates_destination(self):
        headers = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        response = self.client.post(reverse('movement_add', args=[self.diary.pk]), {'to_office': 'New Office', 'remarks': 'Movement note', 'from_office': 'Forged origin'}, **headers)
        self.assertEqual(response.json(), {'success': True})
        self.diary.refresh_from_db()
        movement = self.diary.movements.get()
        self.assertEqual(movement.from_office, 'Office A')
        self.assertEqual(self.diary.marked_to, 'New Office')
        self.assertIn('New Office', self.diary.movement_history_plain())
        self.assertTrue(AuditLog.objects.filter(action='diary.movement.created').exists())
        self.assertEqual(self.client.post(reverse('movement_add', args=[self.foreign.pk]), {'to_office': 'Other Office'}, **headers).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('movement_add', args=[self.diary.pk]), {'to_office': 'Other Office'}, **headers).status_code, 403)

    def test_movement_permission_and_audit_failure_rollback(self):
        from django.contrib.auth.models import Permission
        permission = Permission.objects.get(content_type__app_label='diary', codename='add_diarymovement')
        self.operator.groups.first().permissions.remove(permission)
        self.assertEqual(self.client.get(reverse('movement_add', args=[self.diary.pk])).status_code, 403)
        assign_role_permissions(self.operator)
        with patch('diary.v2_views.audit', side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('movement_add', args=[self.diary.pk]), {'to_office': 'Should roll back'})
        self.diary.refresh_from_db()
        self.assertEqual(self.diary.marked_to, 'Office A')
        self.assertEqual(self.diary.movements.count(), 0)

    def test_invalid_filters_fail_clearly(self):
        for params in [{'month': 13}, {'year': 'evil'}, {'date_from': '2026-02-31'}, {'date_from': '2026-03-02', 'date_to': '2026-03-01'}]:
            self.assertEqual(self.client.get(reverse('diary_list'), params).status_code, 400)
            self.assertEqual(self.client.get(reverse('report_pdf'), params).status_code, 400)

    def test_disabled_directorate_denies_all_diary_access(self):
        self.a.is_active = False
        self.a.save()
        for route in ['dashboard', 'diary_list', 'report_csv', 'report_pdf', 'users']:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_unassigned_and_superuser_without_membership_have_no_diary_access(self):
        user = get_user_model().objects.create_superuser('root', '', 'Secret-password!')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('diary_list')).status_code, 403)
        with self.assertRaises(PermissionDenied):
            scoped_diaries(user)

    def test_system_admin_has_no_implicit_diary_access(self):
        self.client.force_login(self.system)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('users'))
        for route in ['diary_list', 'report_csv', 'report_pdf']:
            self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_system_audit_logs_do_not_disclose_diary_content(self):
        AuditLog.objects.create(user=self.other, directorate=self.b, action='diary.modified', changes={'subject': 'FOREIGN_DIARY_SECRET'})
        self.client.force_login(self.system)
        self.assertNotContains(self.client.get(reverse('audit_logs')), 'FOREIGN_DIARY_SECRET')

    def test_directorate_creation_is_audited(self):
        self.client.force_login(self.system)
        response = self.client.post(reverse('directorate_create'), {'name': 'Engineering', 'code': 'ENG', 'is_active': True})
        self.assertEqual(response.status_code, 302)
        obj = Directorate.objects.get(code='ENG')
        self.assertTrue(DirectorateSettings.objects.filter(directorate=obj).exists())
        self.assertTrue(AuditLog.objects.filter(action='directorate.created', directorate=obj).exists())

    def test_directorate_admin_cannot_create_directorate(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('directorate_create'), {'name': 'Extra', 'code': 'EX'}).status_code, 403)

    def test_user_creation_forces_own_directorate(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('user_create'), {'username': 'new_operator', 'role': 'operator', 'directorate': self.b.pk, 'password': 'A-Strong-Password-938!', 'is_active': True})
        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='new_operator')
        self.assertEqual(user.membership.directorate, self.a)
        self.assertTrue(user.has_perm('diary.add_diary'))
        event = AuditLog.objects.get(action='user.created', record_id=str(user.pk))
        self.assertNotIn('A-Strong-Password', str(event.changes))

    def test_user_create_rejects_role_escalation(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('user_create'), {'username': 'escalate', 'role': 'system', 'directorate': self.a.pk, 'password': 'A-Strong-Password-938!', 'is_active': True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='escalate').exists())

    def test_foreign_user_edit_and_reset_denied(self):
        self.client.force_login(self.admin)
        for route in ['user_edit', 'user_password']:
            self.assertEqual(self.client.get(reverse(route, args=[self.other.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse(route, args=[self.other.pk]), {}).status_code, 404)

    def test_admin_cannot_reset_peer_or_system_account(self):
        self.client.force_login(self.admin)
        for user in [self.admin, self.system]:
            self.assertEqual(self.client.get(reverse('user_password', args=[user.pk])).status_code, 404)

    def test_password_strength_and_reset_token_invalidation(self):
        self.client.force_login(self.admin)
        token = default_token_generator.make_token(self.operator)
        url = reverse('user_password', args=[self.operator.pk])
        response = self.client.post(url, {'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, {'new_password1': 'Changed-Secure-Password-997!', 'new_password2': 'Changed-Secure-Password-997!'})
        self.assertEqual(response.status_code, 302)
        self.operator.refresh_from_db()
        self.assertFalse(default_token_generator.check_token(self.operator, token))
        self.assertTrue(AuditLog.objects.filter(action='password.reset.admin').exists())

    def test_password_change_validation_and_audit(self):
        response = self.client.post(reverse('change_password'), {'old_password': 'S3cure-Office-Password!', 'new_password1': '123', 'new_password2': '123'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('change_password'), {'old_password': 'S3cure-Office-Password!', 'new_password1': 'New-Strong-Password-839!', 'new_password2': 'New-Strong-Password-839!'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse('diary_list')).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action='password.changed').exists())

    def test_login_throttling_and_no_secrets_in_audits(self):
        self.client.logout()
        for _ in range(10):
            self.assertEqual(self.client.post(reverse('login'), {'username': 'unknown', 'password': 'never-log-this'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('login'), {'username': 'unknown', 'password': 'never-log-this'}).status_code, 429)
        self.assertNotIn('never-log-this', str(list(AuditLog.objects.values())))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_reset_link_is_one_time_and_audited(self):
        from django.core import mail
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        self.operator.email = 'operator@example.test'
        self.operator.save()
        self.client.logout()
        response = self.client.post(reverse('password_reset'), {'email': self.operator.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        token = default_token_generator.make_token(self.operator)
        url = reverse('password_reset_confirm', kwargs={'uidb64': urlsafe_base64_encode(force_bytes(self.operator.pk)), 'token': token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        response = self.client.post(response.url, {'new_password1': 'Email-Reset-Password-723!', 'new_password2': 'Email-Reset-Password-723!'})
        self.assertEqual(response.status_code, 302)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password('Email-Reset-Password-723!'))
        self.assertFalse(self.client.get(url).context['validlink'])
        self.assertTrue(AuditLog.objects.filter(action='password.reset.email', user=self.operator).exists())

    def test_auditor_logs_are_scoped_and_viewer_denied(self):
        AuditLog.objects.create(user=self.other, directorate=self.b, action='FOREIGN_EVENT')
        self.client.force_login(self.auditor)
        self.assertNotContains(self.client.get(reverse('audit_logs')), 'FOREIGN_EVENT')
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('audit_logs')).status_code, 403)

    def test_admin_queryset_does_not_bypass_tenant_with_superuser(self):
        from django.contrib import admin
        from django.test import RequestFactory
        self.system.is_superuser = True
        self.system.is_staff = True
        self.system.save()
        request = RequestFactory().get('/admin/')
        request.user = self.system
        self.assertEqual(admin.site._registry[Diary].get_queryset(request).count(), 0)
        self.assertFalse(admin.site._registry[Diary].has_change_permission(request))
        self.assertFalse(admin.site.is_registered(get_user_model()))

    def test_csrf_protects_mutations(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        self.assertEqual(client.post(reverse('diary_create'), self.data()).status_code, 403)


class PostgreSQLCounterTests(TransactionTestCase):
    def test_concurrent_first_registration(self):
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL is required to verify row-lock concurrency guarantees.')
        directorate = Directorate.objects.create(name='Concurrent', code='CON')
        user = account('concurrent', directorate)
        barrier = Barrier(6)
        def register(_):
            connections.close_all()
            try:
                actor = get_user_model().objects.get(pk=user.pk)
                barrier.wait(timeout=15)
                return Diary.create_with_next_number(created_by=actor).sequence
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=6) as executor:
            values = list(executor.map(register, range(6)))
        self.assertEqual(sorted(values), list(range(1, 7)))
        self.assertEqual(DiaryCounter.objects.get(directorate=directorate).value, 6)
