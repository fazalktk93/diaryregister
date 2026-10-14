import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from django.test import SimpleTestCase
from config import instance


class InstanceConfigurationTests(SimpleTestCase):
    def test_database_diagnostic_classifies_failure_without_exposing_secrets(self):
        from config.database_errors import connection_failure_message
        for raw, expected in [
            ('password authentication failed for user private-user password=private-secret', 'Authentication failed'),
            ('connection timed out password=private-secret', 'timed out'),
            ('could not translate host name private-secret', 'could not be resolved'),
            ('SSL certificate private-secret', 'secure connection failed'),
            ('tenant or user not found private-secret', 'Pooler account was not found'),
        ]:
            message = connection_failure_message(Exception(raw), 'pooler.supabase.com')
            self.assertIn(expected, message)
            self.assertNotIn('private-secret', message)
            self.assertNotIn('private-user', message)

    def test_saved_nonsecret_settings_are_reloaded(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.instance.json'
            path.write_text(json.dumps({'database': {'host': 'saved.example'}, 'credential_service': 'cda-test'}), encoding='utf-8')
            with patch.object(instance, 'CONFIG_PATH', path):
                self.assertEqual(instance.read_config()['database']['host'], 'saved.example')
                self.assertNotIn('password', path.read_text())

    def test_env_secret_overrides_keyring_without_reading_it(self):
        with patch.dict(os.environ, {'DB_PASSWORD': 'environment-secret'}), patch.object(instance, 'secret_store') as backend:
            self.assertEqual(instance.credential('DB_PASSWORD', {'credential_service': 'test'}), 'environment-secret')
            backend.assert_not_called()

    def test_keyring_supplies_saved_secret(self):
        backend = Mock()
        backend.get_password.return_value = 'stored-secret'
        with patch.dict(os.environ, {}, clear=True), patch.object(instance, 'secret_store', return_value=backend):
            self.assertEqual(instance.credential('DB_PASSWORD', {'credential_service': 'test'}), 'stored-secret')
            backend.get_password.assert_called_once_with('test', 'DB_PASSWORD')

    def test_plaintext_backend_is_rejected(self):
        import keyring
        class UnsafeBackend:
            pass
        UnsafeBackend.__module__ = 'keyrings.alt.file'
        with patch.object(keyring, 'get_keyring', return_value=UnsafeBackend()):
            with self.assertRaises(RuntimeError):
                instance.secret_store()

    def test_database_environment_fields_override_saved_values(self):
        config = {'database': {'name': 'saved', 'host': 'saved.host', 'port': '5432', 'user': 'saved'}, 'credential_service': 'test'}
        with patch.dict(os.environ, {'DB_HOST': 'new.host', 'DB_NAME': 'new', 'DB_PASSWORD': 'secret'}, clear=True):
            result = instance.database_config(config)
            self.assertEqual(result['NAME'], 'new')
            self.assertEqual(result['HOST'], 'new.host')
            self.assertTrue(result['ATOMIC_REQUESTS'])
            self.assertEqual(result['CONN_MAX_AGE'], 60)
            self.assertTrue(result['CONN_HEALTH_CHECKS'])

    def test_database_url_reuses_connections_and_checks_health(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://user:secret@localhost/database', 'DB_CONN_MAX_AGE': '30'}, clear=True):
            result = instance.database_config({})
            self.assertEqual(result['CONN_MAX_AGE'], 30)
            self.assertTrue(result['CONN_HEALTH_CHECKS'])

    def test_production_database_url_cannot_select_sqlite(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///:memory:'}, clear=True):
            with self.assertRaises(RuntimeError):
                instance.database_config({})
