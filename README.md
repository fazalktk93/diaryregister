# CDA Diary Register v2

A Django diary register for isolated CDA directorates, preserving the original diary fields, file/service-book forms and destination history.

- Dynamic directorates, individual user memberships and role-controlled account management.
- Five-digit diary numbers with independent automatic yearly counters for each directorate.
- Registration dashboard with clickable monthly/yearly totals, search, pagination and filtered PDF/CSV reports.
- Audited registration, edits, archival, account changes and authentication events.
- Validated password changes, administrator resets, optional one-time email reset links and login throttling.
- Responsive Bootstrap 5 templates with persistent light/dark mode and CDA logo branding in navigation, login and PDF reports.
- Sliding desktop sidebar and mobile drawer; diary/user/directorate forms open in modals. Live register search preserves the original quick-entry flow. Add/Save, Cancel, View/Search and Edit actions use green, red, blue and amber accents with text labels.
- Add diary and Movement forms open from the loaded page. Modal saves confirm after the transaction succeeds and refresh displayed records in the background without a full-page reload. Office registration uses a single conflict-safe batch, retaining automatic office choices and tenant isolation.
- One-time PostgreSQL configuration and OS-backed secrets; Waitress on Windows and optional Gunicorn on Linux.

Each ordinary user has one directorate. Server-side membership determines every diary query; browser-supplied directorate IDs are ignored. Disabled directorates cannot access diaries. System administrators manage accounts/directorates without automatic access to diary records. Django Admin is read-only and scoped; all business changes use the audited application interface.

| Role | Access |
| --- | --- |
| System Administrator | Directorates, users, roles, account status, resets and administrative/security audits; no implicit diary access |
| Directorate Administrator | Own directorate's diaries, archival, operator/viewer/auditor accounts, resets, settings and audit logs |
| Data Entry Operator | Own directorate's diary registration, movement, editing, deletion from the active register and reporting |
| Viewer | Own directorate's read-only diary register and reports |
| Auditor | Own directorate's read-only diaries, reports and audit logs |

Diary write actions require both the role and Django model permission. Roles are assigned to Django Groups by the account-management module. Directorate administrators cannot manage peers, system administrators or privileged Django accounts.

Start with [SETUP.md](SETUP.md). Sign in, create directorates and users, then register diaries. New diary dates are set automatically to the current official date (`Asia/Karachi` by default); editing preserves the original date. Dashboard counts, KPI links and reports use the displayed diary date consistently. The register keeps the original View + Movement row actions and modal entry flow; reports provide period/column filters and exports. The PDF preserves the original eight-column oficio-landscape register. Archival preserves the allocated number and historical information.

Main source: `config/` (settings and instance loader), `diary/models.py` (schema), `diary/access.py` (access policy), `diary/v2_views.py`, `v2_forms.py`, `forms.py` and `movement_forms.py` (application), `diary/templates/v2/` (screens), `diary/migrations/`, `diary/tests/`, `setup_instance.py`, `setup_windows.ps1`, `start_windows.bat`, `serve.py`. Original workflow columns and migration history remain for future controlled historical import. Movement records destination changes; workflow status indicators remain outside the primary UI.

Python 3.10+ and Django 5.2 LTS are required. PostgreSQL is the production database. No scheduled backups, cloud deployments or production data imports are included.

Dashboard summaries are cached for 60 seconds and office choices for five minutes, separately for each directorate. Model saves/deletions invalidate the relevant cache after transaction commit; app registration, edits, archival and movement office changes refresh it automatically. Recent diaries, register results, reports and permissions remain live. The local file cache in `.cache/diary-data/` is shared by worker processes on the same machine and requires no additional service. Direct SQL and bulk updates bypass model signals, so their summary changes appear when the cache expires. Test and browser-preview caches are isolated from the running app.

Validation in this workspace: tests use isolated in-memory SQLite; the PostgreSQL concurrency test is skipped until a PostgreSQL test connection is configured. Django checks, migration consistency, Python compilation, PowerShell script parsing and Git whitespace checks passed. Supabase connectivity, OS secret-store persistence and production startup still require configuration on the deployment machine; no production deployment is claimed.
