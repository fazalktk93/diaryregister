# Windows setup and automatic startup

Install Python 3.10+ and, for a local database, PostgreSQL. Run under the Windows account that will run the app; database credentials stay in that account's Windows Credential Manager.

From this repository directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows_app.ps1 -Action Setup
```

The wizard creates the Python environment and installs requirements, then asks for:

- Whether to reuse the existing connection or configure a new one.
- Local PostgreSQL or a remote database, host, port, database name, username, SSL mode and a hidden password.
- Whether to create a missing local database. The supplied database account needs database-creation permission; remote databases are never created by the wizard.
- App bind IP and port, plus LAN IP/hostnames if other PCs will access it. Keep `127.0.0.1` for this PC only; use `0.0.0.0` and explicit allowed LAN hostnames/IPs for LAN access. Windows Firewall access remains manually managed.
- Whether to preview and import the old SQLite backup into the empty local target. Enter `D:\cda backup\db.sqlite3` without surrounding quotes at the path prompt. Import reuses the saved password, preserves the Administration workspace, and refuses a populated target.
- An initial system-administrator account when no active administrator exists. Imported Administration admins already satisfy this check, so their accounts/passwords are retained. On a fresh installation use the system console to create Administration and its users.
- Automatic startup mode, and whether to start the app immediately.

An already-running server started with `start_windows.bat` must first be stopped in its own terminal with Ctrl+C. Managed app processes are stopped before reconfiguration. Non-secret configuration is saved in `.instance.json`, with the previous configuration saved to ignored `.cache/previous-instance.json`. Passwords are never included in task arguments, scripts, configuration JSON or logs. Scheduled and managed launches use the saved settings, clearing competing database/app overrides only in the launched process environment.

## Startup modes

**At Windows sign-in** is the default. It runs under the setup account after a 30-second delay and does not require storing a Windows password in the script.

**At computer boot** is optional. It requires the actual Windows password of the same setup account, not a database password or Windows Hello PIN. Windows Task Scheduler manages that credential. If task registration reports Access denied, run PowerShell as Administrator under the same Windows account and repeat `InstallTask`. Credentials must be available to that account when the task runs.

The task remains running while the app runs, ignores duplicate starts, has no time limit, and retries an unexpected failure up to three times at one-minute intervals. It allows operation on battery. It uses a workspace-specific task name and verifies ownership before modifying or removing a task. The task launches the app hidden; it does not open a browser at each startup. See [Microsoft Task Scheduler settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset) and [task registration](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/register-scheduledtask).

## Day-to-day commands

```powershell
.\windows_app.ps1 -Action Start
.\windows_app.ps1 -Action Status
.\windows_app.ps1 -Action Restart
.\windows_app.ps1 -Action Stop
```

`Start` waits for the login page to respond, then opens the browser. Use `-NoBrowser` to leave it running quietly. Process ownership is checked against the virtual environment, entry point, PID and start time before stopping the app or its child processes. It does not stop unrelated Python processes or PostgreSQL.

Add or change automatic startup without rerunning database setup:

```powershell
.\windows_app.ps1 -Action InstallTask -StartupMode Logon
# Or, to run before sign-in:
.\windows_app.ps1 -Action InstallTask -StartupMode Boot
```

Stop the app and remove automatic startup:

```powershell
.\windows_app.ps1 -Action RemoveTask
```

This retains the database, credentials and app files. `Stop` alone retains the startup task. If PowerShell blocks direct script execution, use the initial `powershell -NoProfile -ExecutionPolicy Bypass -File` syntax with the desired action; it changes policy only for that process.

Logs are in `.runtime/app.stdout.log`, `.runtime/app.stderr.log` and `.runtime/launcher.error.log`. The previous stdout/stderr logs are retained when restarting. Runtime and cache files are ignored by Git. For changes deployed to the same folder, use `Restart`; after moving the repository to another folder, remove the old task and install a task from the new folder.

Validation: configuration/import regression tests, PowerShell syntax checks, a real isolated dummy-server start/stop lifecycle, and mocked registration checks for both startup modes. Actual boot/sign-in execution and Credential Manager access need checking on the deployment account after installation.
