from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse

from ..models import Diary, DiaryMovement
from unittest.mock import patch


class ReportsPdfHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="pdftester", password="pass")
        from diary.models import Directorate, Membership
        tenant = Directorate.objects.create(name='Administration', code='ADM')
        Membership.objects.create(user=self.user, directorate=tenant, role='operator')

    def test_pdf_includes_movement_history_text(self):
        # Create a diary and movements with distinctive to_office strings
        diary = Diary.create_with_next_number(created_by=self.user, diary_date=timezone.localdate(), received_from="Office X")

        DiaryMovement.objects.create(
            diary=diary,
            from_office="X",
            to_office="OFFICE_PDF_B",
            action_type=DiaryMovement.ActionType.FORWARDED,
            action_datetime=timezone.now().replace(day=1),
            remarks="r1",
            created_by=self.user,
        )
        DiaryMovement.objects.create(
            diary=diary,
            from_office="B",
            to_office="OFFICE_PDF_C",
            action_type=DiaryMovement.ActionType.FORWARDED,
            action_datetime=timezone.now().replace(day=2),
            remarks="r2",
            created_by=self.user,
        )

        # Request the PDF for the diary's year
        self.client.force_login(self.user)
        # Inspect the actual report table, including the preserved destination history.
        with patch('diary.v2_views.SimpleDocTemplate.build') as build:
            response = self.client.get(reverse('reports_pdf', args=[diary.year]))
        self.assertEqual(response.status_code, 200)
        data = build.call_args.args[0][-1]._cellvalues
        row = data[1]
        hist_para = row[-1]
        # Paragraph has a getPlainText() helper
        self.assertTrue(hasattr(hist_para, "getPlainText"))
        text = hist_para.getPlainText()
        self.assertIn("OFFICE_PDF_B", text)
        self.assertIn("OFFICE_PDF_C", text)
        # Header rename: ensure column label is 'Movement'
        header = data[0]
        self.assertEqual(header[-1].getPlainText(), "Movement")
