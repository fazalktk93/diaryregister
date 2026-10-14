import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, MagicMock, patch
from django.test import SimpleTestCase
from config import instance


class InstanceConfigurationTests(SimpleTestCase):
    def test_lan_network_configuration_preserves_database_and_credentials(self):
        import setup_instance
        previous = {'database': {'host': 'localhost', 'name': 'existing'}, 'credential_service': 'existing-service',
            'bind_host': '127.0.0.1', 'port': 8000}
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.instance.json'
            path.write_text(json.dumps(previous), encoding='utf-8')
            with patch.object(setup_instance, 'CONFIG_PATH', path), patch.object(setup_instance, 'read_config', return_value=dict(previous)), \
                    patch('builtins.input', side_effect=['', '', '192.168.1.25']), \
                    patch('socket.getaddrinfo', return_value=[]), patch('socket.gethostname', return_value='CDA-PC'), \
                    patch('psycopg2.connect') as connect, patch.object(setup_instance, 'secret_store') as backend:
                setup_instance.configure_network()
            config = json.loads(path.read_text())
            self.assertEqual(config['database'], previous['database'])
            self.assertEqual(config['credential_service'], 'existing-service')
            self.assertEqual(config['bind_host'], '0.0.0.0')
            self.assertIn('192.168.1.25', config['allowed_hosts'])
            connect.assert_not_called()
            backend.assert_not_called()

    def test_lan_defaults_include_detected_server_ip(self):
        import setup_instance
        with patch('builtins.input', side_effect=['0.0.0.0', '', '']), \
                patch('socket.gethostname', return_value='CDA-PC'), \
                patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('192.168.1.25', 0))]):
            result = setup_instance.app_network_settings({})
        self.assertIn('192.168.1.25', result['allowed_hosts'])
        self.assertIn('CDA-PC', result['allowed_hosts'])
        self.assertNotIn('0.0.0.0', result['allowed_hosts'])

    def test_network_hosts_require_server_address_without_url_or_port(self):
        import setup_instance
        with patch('builtins.input', side_effect=['127.0.0.1', '', 'http://192.168.1.25:8000']):
            with self.assertRaises(SystemExit):
                setup_instance.app_network_settings({})
    def test_local_wizard_creates_missing_database_and_stores_only_nonsecrets(self):
        import setup_instance
        import psycopg2
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.instance.json'
            backend, maintenance, verified = Mock(), MagicMock(), MagicMock()
            with patch.object(setup_instance, 'CONFIG_PATH', path), patch.object(setup_instance, 'read_config', return_value={}), \
                    patch.object(setup_instance, 'secret_store', return_value=backend), \
                    patch.object(setup_instance, 'credential', return_value='existing-test-signing-key'), \
                    patch('builtins.input', side_effect=[''] * 8), patch('getpass.getpass', return_value='hidden-test-password'), \
                    patch('psycopg2.connect', side_effect=[psycopg2.OperationalError('database "diaryregister" does not exist'), maintenance, verified]):
                setup_instance.main(local=True, create_database=True, app_settings=True)
            config = json.loads(path.read_text())
            self.assertEqual(config['database']['host'], '127.0.0.1')
            self.assertEqual(config['database']['sslmode'], 'prefer')
            self.assertEqual(config['port'], 8000)
            self.assertIn('127.0.0.1', config['allowed_hosts'])
            self.assertNotIn('hidden-test-password', path.read_text())
            self.assertTrue(maintenance.autocommit)
            maintenance.cursor.return_value.__enter__.return_value.execute.assert_called_once()
            backend.set_password.assert_any_call(config['credential_service'], 'DB_PASSWORD', 'hidden-test-password')
            backend.set_password.assert_any_call(config['credential_service'], 'DJANGO_SECRET_KEY', 'existing-test-signing-key')

    def test_missing_remote_database_is_never_created_by_local_wizard_flag(self):
        import setup_instance
        import psycopg2
        with patch.object(setup_instance, 'read_config', return_value={}), \
                patch('builtins.input', side_effect=['remote.example', '', '', '', '']), \
                patch('getpass.getpass', return_value='test-password'), \
                patch('psycopg2.connect', side_effect=psycopg2.OperationalError('database "postgres" does not exist')) as connect, \
                patch.object(setup_instance, 'secret_store') as backend:
            with self.assertRaises(SystemExit):
                setup_instance.main(create_database=True)
            self.assertEqual(connect.call_count, 1)
            backend.assert_not_called()

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
