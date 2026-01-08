import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.test import Client
from django.contrib.auth import get_user_model
from diary.models import Diary, DiaryMovement
from django.utils import timezone

try:
    User = get_user_model()
    user, created = User.objects.get_or_create(username='testuser', defaults={'password': 'pass'})
    if created:
        user.set_password('pass')
        user.save()
    diary = Diary.create_with_next_number(created_by=user, diary_date=timezone.localdate(), received_from='Office X')
    DiaryMovement.objects.create(
        diary=diary,
        from_office='X',
        to_office='Test Office',
        action_type=DiaryMovement.ActionType.FORWARDED,
        action_datetime=timezone.now(),
        created_by=user
    )

    client = Client()
    client.force_login(user)
    resp = client.get(f'/reports/pdf/{diary.year}/', HTTP_HOST='127.0.0.1')
    print('Status:', resp.status_code)
    print('Content-Type:', resp.get('Content-Type'))
    # Save PDF to file so you can open it locally
    out_path = os.path.join(os.path.dirname(__file__), 'generated_diary_report.pdf')
    with open(out_path, 'wb') as f:
        f.write(resp.content)
    print('Saved PDF to', out_path)
    print('Has Diary No (raw bytes):', b'Diary No' in resp.content)
    print('Has watermark (raw bytes):', b'Administration Directorate Diary System' in resp.content)
    print('Has history (raw bytes):', b'Test Office' in resp.content)
except Exception as e:
    print('Error:', e)