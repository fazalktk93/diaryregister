from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from diary.forms import DiaryCreateForm
from diary.models import Diary, DiaryMovement


class DiaryFormAndHistoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")

    def test_letter_without_folders_is_valid_and_forced_to_zero(self):
        data = {
            "diary_date": timezone.localdate(),
            "received_diary_no": "R-1",
            "received_from": "Office A",
            "file_letter": "Letter",
            # no_of_folders omitted as browser will not send it when disabled
            "subject": "Test",
            "remarks": "",
        }
        form = DiaryCreateForm(data)
        self.assertTrue(form.is_valid(), msg=form.errors.as_json())
        cleaned = form.clean()
        # clean() should set no_of_folders to 0 when Letter is selected
        self.assertEqual(cleaned.get("no_of_folders"), 0)

    def test_movement_history_html_and_plain(self):
        diary = Diary.create_with_next_number(created_by=self.user, diary_date=timezone.localdate(), received_from="Office A")
        # create movements: older ones then a current one
        now = timezone.now()
        DiaryMovement.objects.create(
            diary=diary,
            from_office="A",
            to_office="B",
            action_type=DiaryMovement.ActionType.FORWARDED,
            action_datetime=now.replace(day=1),
            remarks="r1",
            created_by=self.user,
        )
        DiaryMovement.objects.create(
            diary=diary,
            from_office="B",
            to_office="C",
            action_type=DiaryMovement.ActionType.FORWARDED,
            action_datetime=now.replace(day=2),
            remarks="r2",
            created_by=self.user,
        )
        DiaryMovement.objects.create(
            diary=diary,
            from_office="C",
            to_office="D",
            action_type=DiaryMovement.ActionType.MARKED,
            action_datetime=now.replace(day=3),
            remarks="r3",
            created_by=self.user,
        )

        html = diary.movement_history_html()
        plain = diary.movement_history_plain()

        # HTML history should contain strike tags for older entries
        self.assertIn("<s>", html)
        # Plain history must not contain HTML tags and should include office names
        self.assertNotIn("<s>", plain)
        self.assertIn("B", plain)
        self.assertIn("C", plain)
        self.assertIn("D", plain)
