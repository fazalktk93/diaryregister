# Diary Management System - Windows Deployment Setup Script
# Run with: powershell -ExecutionPolicy Bypass -File setup_app.ps1

param(
    [switch]$NoAdmin = $false,
    [switch]$SkipVenv = $false,
    [switch]$SkipDeps = $false
)

# Check if running as administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $NoAdmin) {
    Write-Host "This script requires administrator privileges for firewall and task scheduler setup." -ForegroundColor Yellow
    Write-Host "Restarting as administrator..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList "-ExecutionPolicy", "Bypass", "-File", $MyInvocation.MyCommand.Path -Verb RunAs
    exit
}

Write-Host "================================" -ForegroundColor Green
Write-Host "Diary Management System Setup" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host ""

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Step 1: Check Python
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Cyan
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python and add it to PATH, then run this script again." -ForegroundColor Yellow
    exit 1
}
$pythonVersion = python --version
Write-Host "✓ Found: $pythonVersion" -ForegroundColor Green
Write-Host ""

# Step 2: Create/activate virtual environment
if (-not $SkipVenv) {
    Write-Host "[2/6] Virtual Environment Setup..." -ForegroundColor Cyan
    if (Test-Path "venv\Scripts\activate.ps1") {
        Write-Host "✓ Virtual environment already exists" -ForegroundColor Green
    } else {
        Write-Host "Creating virtual environment..."
        python -m venv venv
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Virtual environment created" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Failed to create virtual environment" -ForegroundColor Red
            exit 1
        }
    }
    
    Write-Host "Activating virtual environment..."
    & "venv\Scripts\activate.ps1"
    Write-Host "✓ Virtual environment activated" -ForegroundColor Green
} else {
    Write-Host "[2/6] Skipping virtual environment setup (as requested)" -ForegroundColor Cyan
}
Write-Host ""

# Step 3: Install dependencies
if (-not $SkipDeps) {
    Write-Host "[3/6] Installing dependencies..." -ForegroundColor Cyan
    if (Test-Path "requirements.txt") {
        Write-Host "Installing from requirements.txt..."
        pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Dependencies installed" -ForegroundColor Green
        } else {
            Write-Host "WARNING: Some dependencies may not have installed correctly" -ForegroundColor Yellow
        }
    } else {
        Write-Host "ERROR: requirements.txt not found" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "[3/6] Skipping dependency installation (as requested)" -ForegroundColor Cyan
}
Write-Host ""

# Step 4: Run Django setup command
Write-Host "[4/6] Running Django setup command..." -ForegroundColor Cyan
python manage.py setup_app
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Setup command encountered an issue" -ForegroundColor Yellow
}
Write-Host ""

# Step 5: Firewall configuration
Write-Host "[5/6] Firewall Configuration..." -ForegroundColor Cyan

# Read the port from settings or ask user
$portInput = Read-Host "Enter the port number for firewall rule (or press Enter for 8000)"
$port = if ($portInput) { [int]$portInput } else { 8000 }

if ($isAdmin) {
    # Check if rule already exists
    $ruleName = "DiaryManagementSystem-Port-$port"
    $existingRule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    
    if ($existingRule) {
        Write-Host "Firewall rule '$ruleName' already exists" -ForegroundColor Yellow
        $updateRule = Read-Host "Update it? (y/n, default n)"
        if ($updateRule -eq 'y') {
            Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -ErrorAction SilentlyContinue | Out-Null
            Write-Host "✓ Firewall rule updated for port $port" -ForegroundColor Green
        }
    } else {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -ErrorAction SilentlyContinue | Out-Null
        Write-Host "✓ Firewall rule created for port $port" -ForegroundColor Green
    }
} else {
    Write-Host "Skipping firewall configuration (requires administrator privileges)" -ForegroundColor Yellow
    Write-Host "To manually create a firewall rule, use Windows Defender Firewall with Advanced Security" -ForegroundColor Gray
}
Write-Host ""

# Step 6: Task Scheduler setup
Write-Host "[6/6] Auto-Start Configuration (Task Scheduler)..." -ForegroundColor Cyan

$taskName = "DiaryManagementSystem"
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask -and $isAdmin) {
    Write-Host "Scheduled task '$taskName' already exists" -ForegroundColor Yellow
    $updateTask = Read-Host "Update/recreate it? (y/n, default n)"
    if ($updateTask -eq 'y') {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "Old task removed" -ForegroundColor Gray
    } else {
        Write-Host "Keeping existing task" -ForegroundColor Yellow
        $updateTask = "n"
    }
} else {
    $updateTask = "y"
}

if ($updateTask -eq 'y' -and $isAdmin) {
    Write-Host "Creating Task Scheduler entry..."
    
    # Get absolute paths
    $pythonExe = (Get-Command python).Source
    $venvPython = "$scriptDir\venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $pythonExe = $venvPython
    }
    
    $manageScript = "$scriptDir\manage.py"
    
    # Create scheduled task
    $action = New-ScheduledTaskAction `
        -Execute $pythonExe `
        -Argument "manage.py runserver 0.0.0.0:$port" `
        -WorkingDirectory $scriptDir
    
    $trigger = New-ScheduledTaskTrigger -AtStartup
    
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RunOnlyIfNetworkAvailable
    
    $principal = New-ScheduledTaskPrincipal -UserID "$env:USERDOMAIN\$env:USERNAME" -RunLevel Highest
    
    Register-ScheduledTask `
        -TaskName $taskName `
        -Description "Diary Management System - Auto-start on Windows startup" `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    
    Write-Host "✓ Scheduled task '$taskName' created for auto-start" -ForegroundColor Green
    Write-Host "  The app will start automatically on system startup" -ForegroundColor Gray
} elseif ($isAdmin) {
    Write-Host "Keeping existing task configuration" -ForegroundColor Green
} else {
    Write-Host "Skipping Task Scheduler setup (requires administrator privileges)" -ForegroundColor Yellow
    Write-Host "To manually start the app, run:" -ForegroundColor Gray
    Write-Host "  python manage.py runserver 0.0.0.0:$port" -ForegroundColor Gray
}
Write-Host ""

# Summary
Write-Host "================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host ""

Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "1. To start the application manually:" -ForegroundColor White
Write-Host "   python manage.py runserver 0.0.0.0:$port" -ForegroundColor Yellow
Write-Host ""
Write-Host "2. Access the application:" -ForegroundColor White
Write-Host "   http://localhost:$port (local only)" -ForegroundColor Yellow
Write-Host "   http://<server-ip>:$port (from other machines)" -ForegroundColor Yellow
Write-Host ""
Write-Host "3. Default superuser setup:" -ForegroundColor White
Write-Host "   See the setup output above for admin credentials" -ForegroundColor Yellow
Write-Host ""

if ($isAdmin) {
    Write-Host "4. Auto-start is configured in Windows Task Scheduler" -ForegroundColor White
    Write-Host "   No further action required" -ForegroundColor Yellow
}
Write-Host ""
