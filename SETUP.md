# Installation and operation

## Prerequisites and Supabase

Install Python 3.10+ (3.12 recommended); on Windows select **Add Python to PATH**. Install PostgreSQL client tools for manual backups. Use a fresh PostgreSQL database. Do not point setup at the historical production database or SQLite file.

For Supabase, create a project, choose a strong database password and obtain PostgreSQL connection details from the project's **Connect** dialog. Use the direct endpoint if IPv6 is available, or the session pooler endpoint for IPv4. Use the provided username and port exactly. Avoid the transaction pooler for this application's migrations/session connections. Default SSL mode is `require`; use `verify-full` with the appropriate trusted CA for certificate verification.

Windows uses Credential Manager through `keyring`. Linux requires an unlocked Secret Service keyring under the same account that runs the server. A headless Linux service can instead receive `DATABASE_URL` and `DJANGO_SECRET_KEY` from a secured service environment; do not commit them or paste them into logs/shell history. Plaintext keyring backends are rejected. Run setup and the application as the same OS user.

## Windows 11

From the repository directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows_app.ps1 -Action Setup
```

The guided wizard creates `.venv`, installs dependencies, prompts for database and app settings, can create a missing local database, optionally imports the historical SQLite backup, applies migrations and collects static files. It creates the first System Administrator only if no administrator exists. Passwords are hidden and stored in the OS credential store. It can install a startup task and start the app. See [WINDOWS_APP.md](WINDOWS_APP.md) for prompts, log locations and startup modes. `setup_windows.ps1` is a compatibility shortcut to this wizard.

Start future sessions with:

```powershell
.\windows_app.ps1 -Action Start
```

Waitress binds to `127.0.0.1:8000` by default. Visit `http://127.0.0.1:8000/login/`. Use `windows_app.ps1 -Action Stop`, `Restart` or `Status` to manage it. `start_windows.bat` remains available for a foreground server stopped with Ctrl+C.

The wizard offers a Windows Task Scheduler task **at logon**, or optionally **at boot** using the same Windows account whose Credential Manager contains the secrets. Use `windows_app.ps1 -Action InstallTask` to install it separately and `RemoveTask` to stop/remove it. Scheduled startup is configured only when you choose it in the wizard or invoke InstallTask.

## One-time configuration and moving servers

```powershell
.\.venv\Scripts\python.exe setup_instance.py
# Equivalent after settings can load:
.\.venv\Scripts\python.exe manage.py setup_instance
.\.venv\Scripts\python.exe manage.py check_database
```

Enter host, port, database, username, SSL mode and hidden password. A successful `SELECT 1` is required before saving. `.instance.json` contains non-secret settings only; the database password and Django secret key are stored in the OS keyring. Both local config and generated files are ignored by Git. Startups reuse them automatically. Rerun the standalone setup script to move to another database; a new Django secret key invalidates existing sessions/reset links. Old keyring entries can be removed manually after verifying the new setup.

Explicit environment variables override stored values: `DATABASE_URL` or `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_SSLMODE`; `DJANGO_SECRET_KEY`, `DJANGO_TIME_ZONE`, `DJANGO_ALLOWED_HOSTS`, `DIARY_BIND_HOST`, `DIARY_PORT`. `DIARY_INSTANCE_CONFIG` selects another configuration path. Never use the test SQLite setting in an office deployment.

For trusted LAN access, explicitly set the bind host to the machine's trusted interface in `.instance.json` or `DIARY_BIND_HOST`, add the hostname to `DJANGO_ALLOWED_HOSTS`, and configure restricted firewall access manually. With HTTPS, set `DJANGO_HTTPS=1`. Set `DJANGO_TRUST_PROXY=1` only behind a trusted proxy that strips/replaces client forwarding headers. DEBUG defaults to disabled.

On Waitress also set `DIARY_TRUSTED_PROXY` to the specific proxy IP (wildcards are rejected). HTTPS mode redirects HTTP requests to HTTPS; configure the TLS proxy before enabling it. HSTS is opt-in via `DJANGO_HSTS_SECONDS`; enable `DJANGO_HSTS_SUBDOMAINS=1` and `DJANGO_HSTS_PRELOAD=1` only after all affected domains are ready for those policies. Default localhost HTTP intentionally produces HTTPS-related warnings from `check --deploy`.

## Linux

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python setup_instance.py
python manage.py check_database
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py create_system_admin
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2
```

Run the setup once, then only the Gunicorn command on subsequent starts. Provide saved OS keyring access or explicit secured environment secrets for the same service account. Gunicorn is installed only on Linux. No application cloud hosting is configured.

## Accounts and passwords

The first System Administrator is an application account, not an unrestricted Django superuser. Sign in and open **Directorates** to create an active directorate, then **User management** to create its Directorate Administrator, operators, viewers and auditors. Newly created directorates can register entries immediately. System Administrators may be assigned one directorate for read-only access; they cannot enumerate diary records across directorates. Account edits include activation/deactivation and role assignment. Directorate administrators manage only operator/viewer/auditor accounts within their directorate.

All users can change their password. Administrators use **Reset password** to set a validated new password when email is unavailable; communicate it privately and ask the user to change it. Resets invalidate the user's existing sessions. No password is stored in audit records.

Email resets are disabled by default with Django's dummy email backend. Configure `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS=True`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL` in the secured process environment. Visit `/password-reset/`. Django's one-time tokens expire after one hour and become invalid after password changes. Email URLs use the request host; allow only trusted hosts and use HTTPS when serving beyond localhost.

Login failures are throttled by account name and source IP for 15 minutes after ten failures. Sessions expire after 30 minutes of inactivity. IP audit values use `REMOTE_ADDR`; untrusted forwarded IPs are ignored.

The register retains View and Movement buttons. Add new diary is available in the left menu. Movement opens the destination-history modal, uses saved offices and allows editing its date/time. Data Entry Operators may edit and move their directorate's diaries; only Directorate Administrators can delete/archive them or see movement "Recorded by" labels. Deletion preserves the number/history. New diary dates are automatic; historical dates are preserved when editing. The desktop sidebar minimises to an icon rail. Reports retain period filters and the original eight-column PDF layout. `python manage.py sync_roles` keeps Movement for admin/operators, adds Delete for admins and removes old operator Delete grants, auditing actual changes. Windows startup runs this synchronization automatically. No diary records or unrelated permissions are changed.

## Manual backup and restore

Supabase Free does not offer the same managed backup guarantees as paid plans. Keep manual off-site exports; hosting does not eliminate backups. See [Supabase backup documentation](https://supabase.com/docs/guides/platform/backups).

With a PostgreSQL client version compatible with your server, use explicit connection parameters and the password prompt (the password is not placed in the command):

```bash
pg_dump --host YOUR_HOST --port 5432 --username YOUR_USER --dbname YOUR_DATABASE --password --schema public --format custom --no-owner --no-acl --file diary-backup.dump
pg_restore --host RESTORE_HOST --port 5432 --username RESTORE_USER --dbname SEPARATE_EMPTY_DATABASE --password --no-owner --no-acl diary-backup.dump
```

Use your actual endpoint's port. Configure SSL for the client, for example `PGSSLMODE=require`. Exporting `public` includes the application's tables and Django migration state, but is not a full Supabase platform backup. Store dumps encrypted, access restricted, off the application computer. Restore only into a separate empty database, then verify counts, users, audit history and diary counters before changing connection settings. Test restores periodically; no automatic backups are implemented.

## Updates, tests and troubleshooting

Stop the application, take a manual backup, update source, reinstall requirements, run `python manage.py migrate`, `python manage.py collectstatic --noinput`, and `python manage.py check`; restart. Test updates against a separate database first.

```bash
python manage.py test diary.tests
python manage.py makemigrations --check --dry-run
```

The normal test suite needs permission to create an isolated `test_` PostgreSQL database (use a separate local/test server, never production). PostgreSQL concurrency tests are skipped on SQLite. For fast non-concurrency checks, PowerShell:

```powershell
$env:DIARY_TEST_SQLITE='1'
python manage.py test diary.tests
Remove-Item Env:DIARY_TEST_SQLITE
```

- Python alias error: install real Python and ensure PATH points to it, rather than the Windows Store alias.
- Connection failed: check Supabase endpoint/port/user, IPv4 session pooler versus direct IPv6, password, project availability and SSL. The connectivity command deliberately omits raw database errors.
- OS keyring unavailable: run under the setup account; unlock Linux Secret Service or use explicitly secured environment secrets. There is no plaintext fallback.
- Login works but diaries return 403: check the account membership, role, active directorate and Django model permissions. System accounts without a directorate are sent to user management.
- Missing styles: Bootstrap assets currently use jsDelivr; network access to that CDN is required. For an offline deployment vendor Bootstrap 5.3.3 locally and update the two asset references in `base.html`.
- Startup reports unapplied migrations: run setup/migrate against the fresh target database, then restart.

For the original single-workspace SQLite backup, use the dedicated local import script documented in [IMPORT_SQLITE.md](IMPORT_SQLITE.md). It maps all imported users and records to Administration, preserves history and numbering, and seeds yearly counters. It requires an empty local PostgreSQL target and does not modify the source backup. Unassigned records remain excluded from normal application queries.
