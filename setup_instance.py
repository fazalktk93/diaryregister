"""Run before Django settings are available; never writes secrets to disk."""
import getpass
import json
import os
import secrets
import uuid
from config.instance import CONFIG_PATH, read_config, secret_store


def connection_failure_message(error, host):
    from config.database_errors import connection_failure_message as describe_failure
    return describe_failure(error, host) + ' Configuration was not changed.'


def main():
    import psycopg2
    previous = read_config()
    db = previous.get('database', {})
    result = {}
    for field, default in [('host', 'localhost'), ('port', '5432'), ('name', 'postgres'), ('user', 'postgres'), ('sslmode', 'require')]:
        default = db.get(field, default)
        result[field] = input(f'PostgreSQL {field} [{default}]: ').strip() or default
    password = getpass.getpass('Database password (hidden): ')
    try:
        with psycopg2.connect(host=result['host'], port=result['port'], dbname=result['name'], user=result['user'], password=password, sslmode=result['sslmode'], connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
    except psycopg2.Error as error:
        raise SystemExit(connection_failure_message(error, result['host'])) from None
    backend = secret_store()
    service = 'cda-diary-' + uuid.uuid4().hex
    backend.set_password(service, 'DB_PASSWORD', password)
    backend.set_password(service, 'DJANGO_SECRET_KEY', secrets.token_urlsafe(64))
    config = {'database': result, 'credential_service': service, 'bind_host': previous.get('bind_host', '127.0.0.1'), 'port': previous.get('port', 8000)}
    temporary = CONFIG_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
    if os.name != 'nt':
        temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)
    print('Connection verified. Configuration saved; credentials are in the OS secret store. Run migrations on a fresh database next.')


if __name__ == '__main__':
    main()
