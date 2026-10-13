"""Local non-secret configuration and operating-system credential storage."""
import json
import os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get('DIARY_INSTANCE_CONFIG', Path(__file__).resolve().parent.parent / '.instance.json'))


def read_config():
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    return {}


def secret_store():
    import keyring
    backend = keyring.get_keyring()
    module = type(backend).__module__
    if not module.startswith(('keyring.backends.Windows', 'keyring.backends.SecretService', 'keyring.backends.macOS')):
        raise RuntimeError('A supported OS credential store is required. On Linux enable Secret Service, or explicitly provide secrets through environment variables.')
    return backend


def credential(name, config):
    if name in os.environ:
        return os.environ[name]
    if not config:
        return None
    return secret_store().get_password(config['credential_service'], name)


def database_config(config):
    if os.environ.get('DIARY_TEST_SQLITE') == '1':
        return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
    if os.environ.get('DATABASE_URL'):
        import dj_database_url
        result = dj_database_url.parse(os.environ['DATABASE_URL'], conn_max_age=60)
        if result['ENGINE'] != 'django.db.backends.postgresql':
            raise RuntimeError('Production requires PostgreSQL.')
        result['ATOMIC_REQUESTS'] = True
        return result
    db = config.get('database', {})
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', db.get('name', 'diaryregister')),
        'HOST': os.environ.get('DB_HOST', db.get('host', 'localhost')),
        'PORT': os.environ.get('DB_PORT', db.get('port', '5432')),
        'USER': os.environ.get('DB_USER', db.get('user', 'postgres')),
        'PASSWORD': credential('DB_PASSWORD', config),
        'OPTIONS': {'sslmode': os.environ.get('DB_SSLMODE', db.get('sslmode', 'require')), 'connect_timeout': 10},
        'ATOMIC_REQUESTS': True,
    }
