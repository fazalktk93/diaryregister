"""Preview/import a legacy SQLite backup into a fresh local PostgreSQL database."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--database', default='diaryregister')
    parser.add_argument('--user', default='postgres')
    parser.add_argument('--port', type=int, default=5432)
    parser.add_argument('--apply', action='store_true', help='Import into localhost PostgreSQL; prompts for the password.')
    parser.add_argument('--configure-app', action='store_true', help='After successful import, save the local app connection with OS-stored credentials.')
    parser.add_argument('--use-saved-connection', action='store_true', help='Use the saved local connection and OS-stored password without prompting again.')
    args = parser.parse_args()
    if args.configure_app and not args.apply:
        parser.error('--configure-app requires --apply')
    saved_password = None
    target_host, sslmode = '127.0.0.1', 'prefer'
    if args.use_saved_connection:
        from config.instance import read_config, credential
        saved = read_config()
        db = saved.get('database', {})
        if db.get('host') not in {'localhost', '127.0.0.1', '::1'}:
            parser.error('The saved connection must target local PostgreSQL, not Supabase.')
        args.database, args.user, args.port = db['name'], db['user'], int(db['port'])
        target_host, sslmode = db['host'], db.get('sslmode', 'prefer')
        saved_password = credential('DB_PASSWORD', saved)
        if not saved_password:
            parser.error('No saved local database password is available for this Windows account.')
    # Never inherit a Supabase connection or a SQLite test override.
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('DIARY_TEST_SQLITE', None)
    secret = secrets.token_urlsafe(64)
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings', DJANGO_SECRET_KEY=secret,
        DIARY_INSTANCE_CONFIG=str(Path(__file__).resolve().parent / '.cache' / 'unused-import-config.json'),
        DB_HOST=target_host, DB_PORT=str(args.port), DB_NAME=args.database,
        DB_USER=args.user, DB_PASSWORD='', DB_SSLMODE=sslmode)
    import django
    django.setup()
    from diary.legacy_import import read_source, prepare_source, source_summary, import_source
    rows = read_source(args.source)
    prepared = prepare_source(rows)
    print(json.dumps(source_summary(rows), indent=2))
    if not args.apply:
        print('Preview only. Source and PostgreSQL were not changed. Add --apply to import into an empty local database.')
        return
    print(f'Target: PostgreSQL {target_host}:{args.port}, database {args.database}. Stop the app before importing.')
    password = saved_password if saved_password is not None else getpass.getpass('Local PostgreSQL password (hidden): ')
    from django.db import connections
    connections['default'].settings_dict['PASSWORD'] = password
    if args.configure_app:
        from config.instance import secret_store
        backend = secret_store()  # Check availability before writing any data.
    from django.core.management import call_command
    # Refuse existing app data before migrations as well as inside the import.
    from django.db import connection
    tables = set(connection.introspection.table_names())
    for table in ('auth_user', 'diary_diary', 'diary_office', 'diary_directorate', 'diary_auditlog'):
        if table in tables:
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT 1 FROM {connection.ops.quote_name(table)} LIMIT 1')
                if cursor.fetchone():
                    raise ValueError('Target contains app data. Create a separate empty PostgreSQL database first.')
    call_command('migrate', interactive=False, verbosity=0)
    import_source(rows, prepared)
    print('Import committed and verified. Password hashes, original numbers and historical timestamps were preserved.')
    if args.configure_app:
        service = 'cda-diary-' + uuid.uuid4().hex
        backend.set_password(service, 'DB_PASSWORD', password)
        backend.set_password(service, 'DJANGO_SECRET_KEY', secret)
        path = Path(__file__).resolve().parent / '.instance.json'
        if path.exists():
            previous = path.parent / '.cache' / 'previous-instance.json'
            previous.parent.mkdir(parents=True, exist_ok=True)
            previous.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
        config = {'database': {'host': target_host, 'port': str(args.port), 'name': args.database,
            'user': args.user, 'sslmode': sslmode}, 'credential_service': service,
            'bind_host': '127.0.0.1', 'port': 8000}
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(config, indent=2), encoding='utf-8')
        temporary.replace(path)
        print('App connection saved for local PostgreSQL. Start with start_windows.bat.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        from django.db import DatabaseError
        if isinstance(error, DatabaseError):
            from config.database_errors import connection_failure_message
            raise SystemExit(connection_failure_message(error, '127.0.0.1') +
                ' Ensure the target database exists. If migrations completed, inspect the source schema; records are imported atomically.') from None
        raise
