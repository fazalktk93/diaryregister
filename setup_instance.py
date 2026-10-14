"""Run before Django settings are available; never writes secrets to disk."""
import getpass
import json
import os
import secrets
import uuid
from config.instance import CONFIG_PATH, read_config, secret_store, credential


def connection_failure_message(error, host):
    from config.database_errors import connection_failure_message as describe_failure
    return describe_failure(error, host) + ' Configuration was not changed.'


def main(*, local=False, create_database=False, app_settings=False):
    import psycopg2
    previous = read_config()
    db = {'host': '127.0.0.1', 'port': '5432', 'name': 'diaryregister', 'user': 'postgres', 'sslmode': 'prefer'} if local else previous.get('database', {})
    result = {}
    for field, default in [('host', 'localhost'), ('port', '5432'), ('name', 'postgres'), ('user', 'postgres'), ('sslmode', 'require')]:
        default = db.get(field, default)
        result[field] = input(f'PostgreSQL {field} [{default}]: ').strip() or default
    password = getpass.getpass('Database password (hidden): ')
    if not 1 <= int(result['port']) <= 65535:
        raise SystemExit('Database port must be between 1 and 65535.')
    connection_args = dict(host=result['host'], port=result['port'], user=result['user'], password=password, sslmode=result['sslmode'], connect_timeout=10)
    try:
        try:
            connection = psycopg2.connect(dbname=result['name'], **connection_args)
        except psycopg2.Error as error:
            missing_database = error.pgcode == '3D000' or ('database' in str(error).lower() and 'does not exist' in str(error).lower())
            if not missing_database or not create_database or result['host'] not in {'localhost', '127.0.0.1', '::1'}:
                raise
            from psycopg2 import sql
            maintenance = psycopg2.connect(dbname='postgres', **connection_args)
            try:
                maintenance.autocommit = True
                with maintenance.cursor() as cursor:
                    cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(result['name'])))
            finally:
                maintenance.close()
            print('Empty local database created.')
            connection = psycopg2.connect(dbname=result['name'], **connection_args)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        connection.close()
    except psycopg2.Error as error:
        raise SystemExit(connection_failure_message(error, result['host'])) from None
    bind_host = previous.get('bind_host', '127.0.0.1')
    app_port = previous.get('port', 8000)
    hosts = previous.get('allowed_hosts', ['127.0.0.1', 'localhost', '[::1]'])
    if app_settings:
        import ipaddress
        bind_host = input(f'App bind IP (127.0.0.1 for this PC, 0.0.0.0 for LAN) [{bind_host}]: ').strip() or bind_host
        ipaddress.ip_address(bind_host)
        app_port = int(input(f'App port [{app_port}]: ').strip() or app_port)
        if not 1 <= app_port <= 65535:
            raise SystemExit('App port must be between 1 and 65535.')
        extra_hosts = input('LAN IP/hostnames allowed in the browser (comma-separated, blank for local only): ').strip()
        bound_host = f'[{bind_host}]' if ':' in bind_host else bind_host
        hosts = list(dict.fromkeys(['127.0.0.1', 'localhost', '[::1]'] +
            ([bound_host] if bind_host not in {'0.0.0.0', '::'} else []) +
            [host.strip() for host in extra_hosts.split(',') if host.strip()]))
        for host in hosts:
            if host.startswith('[') and host.endswith(']'):
                ipaddress.ip_address(host[1:-1])
            elif any(char in host for char in ('*', '/', ':', ' ')) or host.startswith('.'):
                raise SystemExit('Enter explicit hostnames/IPs without URLs, ports or wildcards; bracket IPv6 addresses.')
    backend = secret_store()
    service = 'cda-diary-' + uuid.uuid4().hex
    backend.set_password(service, 'DB_PASSWORD', password)
    backend.set_password(service, 'DJANGO_SECRET_KEY', credential('DJANGO_SECRET_KEY', previous) or secrets.token_urlsafe(64))
    config = {'database': result, 'credential_service': service, 'bind_host': bind_host, 'port': app_port, 'allowed_hosts': hosts}
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.parent / '.cache' / 'previous-instance.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(CONFIG_PATH.read_text(encoding='utf-8'), encoding='utf-8')
    temporary = CONFIG_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
    if os.name != 'nt':
        temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)
    print('Connection verified. Configuration saved; credentials are in the OS secret store. Run migrations on a fresh database next.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--create-database', action='store_true')
    parser.add_argument('--app-settings', action='store_true')
    args = parser.parse_args()
    main(local=args.local, create_database=args.create_database, app_settings=args.app_settings)
