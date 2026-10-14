# Import the original SQLite backup into local PostgreSQL

Use `import_sqlite_to_postgres.py` from the repository directory. It reads the backup in read-only mode. It always targets `127.0.0.1`, ignoring any inherited Supabase URL, database settings or SQLite test override. Preview is the default and does not connect to PostgreSQL.

The supplied backup contains 8 users, 6,775 diaries, 16,413 movements, 740 offices and 98 Django admin-history events. The single workspace becomes **Administration** with the PDF title **Administration Directorate**. The 2026 counter is seeded to 6,775, so the next 2026 diary is **06776**.

User IDs, password hashes, active/staff/superuser flags, usernames and account information are preserved. Original diary and movement IDs, numbers, references, fields and timestamps are preserved. Naive historical Django timestamps are interpreted as UTC. Admin-history events are retained as tenant-scoped audit events. The old application configuration is retained in its legacy table.

Existing admin-group members, staff and superusers become Administration directorate admins. Clerk-only accounts become operators; readers and accounts without recognized groups become viewers. Admin membership takes precedence when old groups overlap. In this particular backup the result is **6 admins and 2 viewers**. Every imported user belongs to Administration; no imported account is assigned the separate system-administrator role. Current role groups are generated instead of copying obsolete permission/content-type IDs.

Old login sessions and old Django migration state are not copied. Users sign in with their existing passwords. The target schema is created by the current app's migrations.

## Run the import

1. Install PostgreSQL and use pgAdmin to create a **new empty database**, for example `diaryregister_import`, owned by `postgres`. Stop the app. Do not run app setup/create-system-admin against this new database before importing: existing app users/data make the importer refuse to proceed.
2. Preview and validate the backup:

```powershell
.\.venv\Scripts\python.exe import_sqlite_to_postgres.py "D:\cda backup\db.sqlite3"
```

3. Import and switch this app to local PostgreSQL:

```powershell
.\.venv\Scripts\python.exe import_sqlite_to_postgres.py "D:\cda backup\db.sqlite3" --database diaryregister_import --apply --configure-app
```

Enter the **local PostgreSQL** password at the hidden prompt. No password is written into a script, command argument or JSON file. `--configure-app` stores credentials in the OS credential store and updates `.instance.json` only after the import succeeds. The previous connection configuration, if present, is saved to ignored `.cache/previous-instance.json`; its OS credentials remain intact. Omit `--configure-app` to import without changing the app connection. Use `--user` or `--port` if your local installation differs from the defaults.

4. Start the app:

```powershell
.\start_windows.bat
```

All app-data inserts run in one transaction. The script checks source integrity, references, numbering, field compatibility and imported counts; failures roll back the import. Existing target app data is never overwritten, merged or deleted. Re-running against a populated target is refused. PostgreSQL identity sequences are reset after the original IDs are inserted. Cache namespaces are isolated by database, and imported cache data is invalidated after commit.

If import fails after schema migrations, the new schema may remain, but app records are rolled back. Fix the cause and retry against that still-empty database. Keep the original SQLite backup for comparison and recovery.
