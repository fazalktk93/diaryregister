@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Setup is incomplete. Run setup_windows.ps1 first.
  exit /b 1
)
".venv\Scripts\python.exe" serve.py
if errorlevel 1 (
  echo Startup failed. Check setup, database connectivity and pending migrations.
  pause
  exit /b 1
)
