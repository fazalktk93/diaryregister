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


def app_network_settings(previous, *, lan_default=False):
    import ipaddress
    import socket
    bind_host = '0.0.0.0' if lan_default else previous.get('bind_host', '127.0.0.1')
    bind_host = input(f'App bind IP (127.0.0.1 for this PC, 0.0.0.0 for LAN) [{bind_host}]: ').strip() or bind_host
    ipaddress.ip_address(bind_host)
    port = int(input(f'App port [{previous.get("port", 8000)}]: ').strip() or previous.get('port', 8000))
    if not 1 <= port <= 65535:
        raise SystemExit('App port must be between 1 and 65535.')
    base_hosts = ['127.0.0.1', 'localhost', '[::1]']
    extras = [host for host in previous.get('allowed_hosts', []) if host not in base_hosts + ['::1', '0.0.0.0', '[::]']]
    if bind_host in {'0.0.0.0', '::'} and not extras:
        try:
            extras = sorted({entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                if not ipaddress.ip_address(entry[4][0]).is_loopback})
        except OSError:
            extras = []
        extras.append(socket.gethostname())
    defaults = ','.join(extras)
    extra_hosts = input(f'Server LAN IP/hostnames used in browser URLs (not client PC IPs) [{defaults}]: ').strip() or defaults
    bound_host = f'[{bind_host}]' if ':' in bind_host else bind_host
    hosts = list(dict.fromkeys(base_hosts + ([bound_host] if bind_host not in {'0.0.0.0', '::'} else []) +
        [host.strip() for host in extra_hosts.split(',') if host.strip()]))
    for host in hosts:
        if host.startswith('[') and host.endswith(']'):
            ipaddress.ip_address(host[1:-1])
        elif any(char in host for char in ('*', '/', ':', ' ')) or host.startswith('.'):
            raise SystemExit('Enter server IPs/hostnames without http://, ports or wildcards; bracket IPv6 addresses.')
    return {'bind_host': bind_host, 'port': port, 'allowed_hosts': hosts}


def save_config(config):
    if CONFIG_PATH.exists():
        backup = CONFIG_PATH.parent / '.cache' / 'previous-instance.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(CONFIG_PATH.read_text(encoding='utf-8'), encoding='utf-8')
    temporary = CONFIG_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
    if os.name != 'nt':
        temporary.chmod(0o600)
    temporary.replace(CONFIG_PATH)


def configure_network():
    config = read_config()
    if not config:
        raise SystemExit('Initial setup is incomplete. Run windows_app.ps1 -Action Setup first.')
    config.update(app_network_settings(config, lan_default=True))
    save_config(config)
    print('Network settings saved. Database and OS credentials were retained. Restart the app.')
    for host in config['allowed_hosts']:
        if host not in {'127.0.0.1', 'localhost', '[::1]'}:
            print(f'Other PCs can use: http://{host}:{config["port"]}/')


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
    network = {'bind_host': previous.get('bind_host', '127.0.0.1'), 'port': previous.get('port', 8000),
        'allowed_hosts': previous.get('allowed_hosts', ['127.0.0.1', 'localhost', '[::1]'])}
    if app_settings:
        network = app_network_settings(previous)
    backend = secret_store()
    service = 'cda-diary-' + uuid.uuid4().hex
    backend.set_password(service, 'DB_PASSWORD', password)
    backend.set_password(service, 'DJANGO_SECRET_KEY', credential('DJANGO_SECRET_KEY', previous) or secrets.token_urlsafe(64))
    config = {'database': result, 'credential_service': service, **network}
    save_config(config)
    print('Connection verified. Configuration saved; credentials are in the OS secret store. Run migrations on a fresh database next.')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true')
    parser.add_argument('--create-database', action='store_true')
    parser.add_argument('--app-settings', action='store_true')
    parser.add_argument('--network-only', action='store_true', help='Configure LAN access without changing the database or passwords.')
    args = parser.parse_args()
    if args.network_only:
        configure_network()
    else:
        main(local=args.local, create_database=args.create_database, app_settings=args.app_settings)
