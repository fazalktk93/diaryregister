"""Production Windows entry point; uses saved settings and a trusted bind address."""
import os
from config.instance import read_config


def main():
    config = read_config()
    if not config and not (os.environ.get('DJANGO_SECRET_KEY') and (os.environ.get('DATABASE_URL') or os.environ.get('DB_PASSWORD'))):
        raise SystemExit('Initial setup is incomplete. Run setup_windows.ps1 first.')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    from django.core.management import call_command
    import django
    django.setup()
    call_command('check_database')
    call_command('migrate', check_unapplied=True)
    call_command('sync_roles')
    call_command('collectstatic', interactive=False, verbosity=0)
    from waitress import serve
    from config.wsgi import application
    host = os.environ.get('DIARY_BIND_HOST', config.get('bind_host', '127.0.0.1'))
    port = int(os.environ.get('DIARY_PORT', config.get('port', 8000)))
    print(f'CDA Diary Register: http://{host}:{port}', flush=True)
    proxy_options = {}
    if os.environ.get('DJANGO_TRUST_PROXY') == '1':
        trusted_proxy = os.environ.get('DIARY_TRUSTED_PROXY')
        if not trusted_proxy or trusted_proxy == '*':
            raise SystemExit('Set DIARY_TRUSTED_PROXY to the specific trusted proxy address before enabling proxy headers.')
        proxy_options = {'trusted_proxy': trusted_proxy, 'trusted_proxy_headers': {'x-forwarded-proto'}}
    serve(application, host=host, port=port, threads=8, **proxy_options)


if __name__ == '__main__':
    from django.core.management.base import CommandError
    try:
        main()
    except CommandError as error:
        raise SystemExit(str(error)) from None
