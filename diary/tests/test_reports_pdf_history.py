from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse

from ..models import Diary, DiaryMovement
from .. import views


class ReportsPdfHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="pdftester", password="pass")

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
        # Instead of parsing PDF bytes (compressed), call the internal data
        # builder logic to assert the history text is present in the table data.
        data = views._build_pdf_data_for_year(diary.year)
        # last column of the first data row should be a Paragraph with plain text
        # Note: data[0] is the header row, so check data[1]
        row = data[1]
        hist_para = row[-1]
        # Paragraph has a getPlainText() helper
        self.assertTrue(hasattr(hist_para, "getPlainText"))
        text = hist_para.getPlainText()
        self.assertIn("OFFICE_PDF_B", text)
        self.assertIn("OFFICE_PDF_C", text)
