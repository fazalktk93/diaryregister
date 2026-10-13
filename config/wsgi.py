import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
from django.conf import settings
from .instance import credential
if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise RuntimeError('Application serving requires PostgreSQL; SQLite is reserved for isolated tests.')
if not credential('DJANGO_SECRET_KEY', settings.INSTANCE):
    raise RuntimeError('Initial setup is incomplete. Run setup_instance.py or provide a secure DJANGO_SECRET_KEY.')
