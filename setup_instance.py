"""Run before Django settings are available; never writes secrets to disk."""
import getpass
import json
import os
import secrets
import uuid
from config.instance import CONFIG_PATH, read_config, secret_store


def connection_failure_message(error, host):
    """Classify errors without printing raw messages that may contain secrets."""
    message = str(error).lower()
    if 'password authentication failed' in message or getattr(error, 'pgcode', None) == '28P01':
        reason = 'Authentication failed. Check the database password and the exact username from Supabase Connect.'
    elif 'tenant or user not found' in message:
        reason = 'Pooler account was not found. Copy the session-pooler host and username from the same Supabase project.'
    elif any(term in message for term in ('network is unreachable', 'no route to host', 'cannot assign requested address')):
        reason = 'The database network address is unreachable from this computer.'
    elif any(term in message for term in ('could not translate host name', 'name or service not known', 'getaddrinfo failed')):
        reason = 'The database hostname could not be resolved. Check the hostname and network connectivity.'
    elif 'timeout' in message or 'timed out' in message:
        reason = 'The database connection timed out. Check network access, firewall rules and project availability.'
    elif 'ssl' in message or 'certificate' in message:
        reason = 'The secure connection failed. Check SSL mode and any required CA certificate.'
    else:
        reason = 'Check host, port, database, username, password, SSL mode and network access.'
    if host.endswith('.supabase.co') and host.startswith('db.'):
        reason += ' This is a Supabase direct endpoint, which normally requires IPv6. On an IPv4 network, select Connect > Session pooler and use its host and username instead.'
    return 'Database connection failed. ' + reason + ' Configuration was not changed.'


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
