# Diary Management System - Windows Deployment Guide

## Overview

The Diary Management System can be deployed on Windows across different directorates with minimal configuration. This guide covers the complete setup process.

## Quick Start (Recommended)

On a fresh Windows machine, run:

```powershell
# Open PowerShell as Administrator, then navigate to the project directory
powershell -ExecutionPolicy Bypass -File setup_app.ps1
```

This single command will:
1. Create a Python virtual environment
2. Install all dependencies from `requirements.txt`
3. Run interactive configuration (directorate name, port, host)
4. Set up database migrations
5. Create Windows Firewall exceptions
6. Configure auto-start via Task Scheduler

## Manual Setup Steps

If you prefer manual control, follow these steps:

### 1. Prerequisites

- Python 3.9+ installed and added to PATH
- Git (for cloning the repository)
- Windows 10/11 with administrator access
- Database (SQLite by default - no external setup needed)

### 2. Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
venv\Scripts\activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Database Setup

```bash
# Run migrations
python manage.py migrate
```

### 5. Configure the Application

```bash
# Interactive configuration
python manage.py setup_app
```

This will ask you for:
- **Directorate Name** - Used in PDF report titles (e.g., "Administration Directorate")
- **Port** - Server port (default: 8000)
- **Host** - IP/hostname to bind to (default: 0.0.0.0 for network access)
- **Superuser** - Admin credentials

### 6. Run the Application

```bash
# Manual start
python manage.py runserver 0.0.0.0:8000
```

Or access the configured auto-start task (if you ran the PowerShell script).

## Configuration Details

### Where Settings Are Stored

Application configuration is stored in the database:
- **Model**: `diary.models.AppConfig` (singleton)
- **Fields**:
  - `directorate_name` - Organization name for reports
  - `port` - Server port (used by your run command)
  - `host` - Bind address (0.0.0.0 = all interfaces)

### Retrieving Current Configuration

```bash
python manage.py shell
>>> from diary.models import AppConfig
>>> config = AppConfig.get_config()
>>> print(config.directorate_name, config.port, config.host)
```

### Updating Configuration Later

Run the setup command again:
```bash
python manage.py setup_app
```

It will let you update any setting.

## Network Access

### Local Machine Only
```
http://localhost:8000
```

### From Other Machines on the Network

If the server is bound to `0.0.0.0:8000`:
```
http://<server-ip>:8000
```

**Note**: Windows Firewall must allow the port. The PowerShell setup script creates this rule automatically, or you can manually add it via Windows Defender Firewall settings.

## Firewall Configuration

### Automatic (PowerShell Script)
The setup script creates a rule named `DiaryManagementSystem-Port-<port>`.

### Manual
1. Open "Windows Defender Firewall with Advanced Security"
2. Click "New Rule..."
3. Select "Port"
4. Choose "TCP" and enter your port number
5. Select "Allow"
6. Check all three profiles (Domain, Private, Public)
7. Name it "DiaryManagementSystem-Port-8000" (or your port number)

## Auto-Start Configuration

### Task Scheduler (Created by PowerShell Script)

The setup script creates a scheduled task:
- **Task Name**: `DiaryManagementSystem`
- **Trigger**: At system startup
- **Action**: Runs `python manage.py runserver 0.0.0.0:<port>`
- **User**: Current logged-in user (runs with elevated privileges)

### Verify the Task

```powershell
Get-ScheduledTask -TaskName "DiaryManagementSystem"
```

### Disable/Re-enable Auto-Start

```powershell
# Disable
Disable-ScheduledTask -TaskName "DiaryManagementSystem"

# Re-enable
Enable-ScheduledTask -TaskName "DiaryManagementSystem"

# Remove completely
Unregister-ScheduledTask -TaskName "DiaryManagementSystem" -Confirm:$false
```

## PDF Report Titles

The directorate name you configure appears in PDF reports as:
```
Diary Record of {directorate_name}
Year {year}
```

If not configured:
```
Diary Record
Year {year}
```

## Troubleshooting

### Port Already in Use

If the configured port is already in use:
1. Run `setup_app` again and choose a different port
2. Or find the process using the port and stop it:
   ```powershell
   netstat -ano | findstr :8000  # Shows PID using port 8000
   taskkill /PID <PID> /F        # Kill the process
   ```

### Auto-Start Not Working

1. Check the Task Scheduler task exists:
   ```powershell
   Get-ScheduledTask -TaskName "DiaryManagementSystem"
   ```

2. Check the task last run result:
   ```powershell
   Get-ScheduledTaskInfo -TaskName "DiaryManagementSystem"
   ```

3. Re-run the PowerShell setup script to recreate it.

### Permission Denied Errors

- Run PowerShell as Administrator
- Re-run the PowerShell setup script with `-NoAdmin` flag to skip admin-only steps

### Database Errors

Ensure migrations are applied:
```bash
python manage.py migrate
```

## File Locations

| Item | Location |
|------|----------|
| App directory | `C:\Users\<user>\diaryregister` |
| Database | `C:\Users\<user>\diaryregister\db.sqlite3` |
| Virtual environment | `C:\Users\<user>\diaryregister\venv` |
| Configuration | Database (AppConfig model) |
| Setup script | `C:\Users\<user>\diaryregister\setup_app.ps1` |
| Management command | `diary\management\commands\setup_app.py` |

## Security Notes

1. **Superuser Credentials**: Create a strong password for the admin account
2. **Database**: By default uses SQLite. For production, consider PostgreSQL or MySQL
3. **Debug Mode**: Ensure `DEBUG = False` in production settings
4. **Secret Key**: Check that `SECRET_KEY` in `config/settings.py` is unique
5. **Allowed Hosts**: Configure `ALLOWED_HOSTS` in `config/settings.py` for your domain

## Updating Configuration

To change directorate name, port, or host later:

```bash
# Activate virtual environment
venv\Scripts\activate.ps1

# Run setup
python manage.py setup_app
```

The setup command is safe to run multiple times - it updates without conflicts.

## Uninstalling

To remove the application:

1. Delete the Task Scheduler task:
   ```powershell
   Unregister-ScheduledTask -TaskName "DiaryManagementSystem" -Confirm:$false
   ```

2. Remove the firewall rule:
   ```powershell
   Remove-NetFirewallRule -DisplayName "DiaryManagementSystem-Port-8000"
   ```

3. Delete the application directory:
   ```powershell
   Remove-Item -Path "C:\path\to\diaryregister" -Recurse -Force
   ```

## Support

For issues or questions, refer to the Django documentation or the project's issue tracker.
