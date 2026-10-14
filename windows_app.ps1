[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Start', 'Stop', 'Restart', 'Status', 'InstallTask', 'RemoveTask', 'Run')]
    [string]$Action = 'Setup',
    [ValidateSet('Logon', 'Boot')][string]$StartupMode = 'Logon',
    [ValidatePattern('^[a-zA-Z0-9 ._-]+$')][string]$TaskName,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$workspacePath = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonPath = Join-Path $workspacePath '.venv\Scripts\python.exe'
$serverPath = Join-Path $workspacePath 'serve.py'
$scriptPath = Join-Path $workspacePath 'windows_app.ps1'
$runtimePath = Join-Path $workspacePath '.runtime'
$statePath = Join-Path $runtimePath 'process.json'
$stdoutPath = Join-Path $runtimePath 'app.stdout.log'
$stderrPath = Join-Path $runtimePath 'app.stderr.log'
$launcherErrorPath = Join-Path $runtimePath 'launcher.error.log'
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not $TaskName) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $workspaceHash = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($workspacePath.ToLowerInvariant())))).Replace('-', '').Substring(0, 8) }
    finally { $hasher.Dispose() }
    $TaskName = "CDA Diary Register $workspaceHash"
}
Set-Location -LiteralPath $workspacePath

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Executable $($Arguments -join ' ')" }
}
function Ask-YesNo {
    param([string]$Question, [bool]$Default = $false)
    while ($true) {
        $suffix = if ($Default) { '[Y/n]' } else { '[y/N]' }
        $answer = (Read-Host "$Question $suffix").Trim().ToLowerInvariant()
        if (-not $answer) { return $Default }
        if ($answer -in @('y', 'yes')) { return $true }
        if ($answer -in @('n', 'no')) { return $false }
    }
}
function Use-SavedEnvironment {
    # Process-local only: scheduled runs use the wizard's saved settings.
    foreach ($name in @('DATABASE_URL', 'DB_HOST', 'DB_PORT', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_SSLMODE',
        'DIARY_TEST_SQLITE', 'DIARY_INSTANCE_CONFIG', 'DJANGO_SECRET_KEY', 'DJANGO_SETTINGS_MODULE',
        'DIARY_BIND_HOST', 'DIARY_PORT', 'DJANGO_ALLOWED_HOSTS')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}
function Read-Instance {
    $path = Join-Path $workspacePath '.instance.json'
    if (-not (Test-Path -LiteralPath $path)) { throw 'Run windows_app.ps1 -Action Setup first.' }
    return Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}
function Get-OwnedTask {
    $task = Get-ScheduledTask -TaskName $TaskName -TaskPath '\' -ErrorAction SilentlyContinue
    if ($task) {
        $expected = "-File `"$scriptPath`""
        if ($task.Description -ne "CDA Diary Register workspace: $workspacePath" -or
            @($task.Actions | Where-Object { $_.Execute -eq $powershellPath -and $_.Arguments.Contains($expected) -and $_.Arguments.Contains('-Action Run') }).Count -ne 1) {
            throw "Task '$TaskName' belongs to another application. Choose a different -TaskName."
        }
    }
    return $task
}
function Get-OwnedProcess {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ($state.entry_point -ne $serverPath -or $state.python -ne $pythonPath) { return $null }
        $process = Get-Process -Id ([int]$state.process_id) -ErrorAction SilentlyContinue
        if (-not $process -or $process.HasExited) { return $null }
        if ([Math]::Abs(($process.StartTime.ToUniversalTime() - [DateTime]::Parse($state.started).ToUniversalTime()).TotalSeconds) -gt 1) { return $null }
        $details = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
        if ($details.ExecutablePath -ne $pythonPath -or $details.CommandLine -notmatch [Regex]::Escape($serverPath)) { return $null }
        return $process
    } catch { return $null }
}
function Stop-OwnedProcessTree {
    $process = Get-OwnedProcess
    if (-not $process) { return }
    # Verify the root before following its children (Windows venv launchers may spawn Python).
    $allProcesses = @(Get-CimInstance Win32_Process)
    $ownedIds = @([int]$process.Id)
    $frontier = @([int]$process.Id)
    while ($frontier.Count) {
        $children = @($allProcesses | Where-Object { $_.ParentProcessId -in $frontier -and $_.ProcessId -notin $ownedIds } | ForEach-Object { [int]$_.ProcessId })
        $ownedIds += $children; $frontier = $children
    }
    [Array]::Reverse($ownedIds)
    foreach ($processId in $ownedIds) { Stop-Process -Id $processId -ErrorAction SilentlyContinue }
}
function Stop-App {
    $task = Get-OwnedTask
    $managedProcess = Get-OwnedProcess
    # Stop the verified tree before stopping its scheduler supervisor.
    Stop-OwnedProcessTree
    if ($task -and $task.State -eq 'Running') { Stop-ScheduledTask -TaskName $TaskName -TaskPath '\' }
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
    if ($managedProcess) { Write-Host 'App stopped. Automatic startup remains installed until RemoveTask is used.' }
    else { Write-Host 'No managed app process is running. Servers started in another terminal must be stopped there with Ctrl+C.' }
}
function Run-App {
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment missing. Run Setup first.' }
    $config = Read-Instance
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    $lockPath = Join-Path $runtimePath 'control.lock'
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    try {
        if (Get-OwnedProcess) { return }
        if (Test-Path -LiteralPath $launcherErrorPath) { Remove-Item -LiteralPath $launcherErrorPath }
        if (Get-NetTCPConnection -LocalPort ([int]$config.port) -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $($config.port) is already in use. Stop the existing server (Ctrl+C) or choose another app port."
        }
        foreach ($logPath in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $logPath) { Move-Item -LiteralPath $logPath -Destination ($logPath + '.previous') -Force }
        }
        Use-SavedEnvironment
        $process = Start-Process -FilePath $pythonPath -ArgumentList "`"$serverPath`"" -WorkingDirectory $workspacePath `
            -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
        $process.Handle | Out-Null
        $state = @{ process_id = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); python = $pythonPath; entry_point = $serverPath }
        $temporaryState = Join-Path $runtimePath 'process.tmp'
        $state | ConvertTo-Json | Set-Content -LiteralPath $temporaryState -Encoding UTF8
        Move-Item -LiteralPath $temporaryState -Destination $statePath -Force
    } finally { $lock.Dispose() }
    # Remain running so Task Scheduler can detect a crash and restart the app.
    try { $process.WaitForExit(); $process.Refresh(); $exitCode = $process.ExitCode }
    finally {
        if (Test-Path -LiteralPath $statePath) {
            $current = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ($current.process_id -eq $process.Id) { Remove-Item -LiteralPath $statePath }
        }
    }
    if ($exitCode -ne 0) { throw "App exited with code $exitCode. See $stderrPath" }
}
function Install-StartupTask {
    Read-Instance | Out-Null
    Get-OwnedTask | Out-Null
    $accountName = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $taskAction = New-ScheduledTaskAction -Execute $powershellPath -WorkingDirectory $workspacePath `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`" -Action Run -TaskName `"$TaskName`" -NoBrowser"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $description = "CDA Diary Register workspace: $workspacePath"
    if ($StartupMode -eq 'Boot') {
        Write-Host 'Boot startup needs the password of this Windows account, not your database password or Windows Hello PIN.'
        $credential = Get-Credential -UserName $accountName -Message 'Windows account used for setup and Credential Manager'
        if (-not $credential -or $credential.UserName -ne $accountName) { throw "Use the same Windows account: $accountName" }
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $trigger.Delay = 'PT30S'
        $nativePassword = $credential.GetNetworkCredential().Password
        try {
            Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $taskAction -Trigger $trigger -Settings $settings `
                -Description $description -User $accountName -Password $nativePassword -RunLevel Limited -Force | Out-Null
        } finally { $nativePassword = $null; $credential = $null }
    } else {
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $accountName
        $trigger.Delay = 'PT30S'
        $principal = New-ScheduledTaskPrincipal -UserId $accountName -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Action $taskAction -Trigger $trigger -Settings $settings `
            -Principal $principal -Description $description -Force | Out-Null
    }
    Write-Host "Automatic startup installed: $TaskName ($StartupMode), under $accountName."
}
function Start-App {
    $config = Read-Instance
    if (-not (Get-OwnedProcess)) {
        if (Test-Path -LiteralPath $launcherErrorPath) { Remove-Item -LiteralPath $launcherErrorPath }
        $task = Get-OwnedTask
        if ($task) { Start-ScheduledTask -TaskName $TaskName -TaskPath '\' }
        else {
            Start-Process -FilePath $powershellPath -WorkingDirectory $workspacePath -WindowStyle Hidden `
                -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`" -Action Run -TaskName `"$TaskName`" -NoBrowser" | Out-Null
        }
    }
    $browserHost = [string]$config.bind_host
    if ($browserHost -eq '0.0.0.0') { $browserHost = '127.0.0.1' }
    elseif ($browserHost -eq '::') { $browserHost = '[::1]' }
    elseif ($browserHost.Contains(':')) { $browserHost = "[$browserHost]" }
    $address = "http://${browserHost}:$($config.port)"
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    Write-Host 'Starting app...'
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Get-OwnedProcess) {
            try {
                $response = Invoke-WebRequest -Uri "$address/login/" -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    Write-Host "App ready: $address"
                    if (-not $NoBrowser) { Start-Process $address }
                    return
                }
            } catch { }
        }
        elseif (Test-Path -LiteralPath $launcherErrorPath) { throw (Get-Content -LiteralPath $launcherErrorPath -Raw) }
        Start-Sleep -Milliseconds 500
    }
    throw "App did not become ready within 60 seconds. Check $stderrPath and Task Scheduler's Last Run Result."
}
function Setup-App {
    Stop-App
    Use-SavedEnvironment
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        $python = Get-Command python -ErrorAction Stop
        Invoke-Checked $python.Source @('-m', 'venv', (Join-Path $workspacePath '.venv'))
    }
    Invoke-Checked $pythonPath @('-m', 'pip', 'install', '-r', (Join-Path $workspacePath 'requirements.txt'))
    $instancePath = Join-Path $workspacePath '.instance.json'
    $reuse = (Test-Path -LiteralPath $instancePath) -and (Ask-YesNo 'Use the saved database and app settings?' $false)
    if (-not $reuse) {
        $configurationArgs = @('setup_instance.py', '--app-settings')
        if (Ask-YesNo 'Use PostgreSQL installed on this PC?' $true) {
            $configurationArgs += '--local'
            if (Ask-YesNo 'Create the database if it does not exist?' $true) { $configurationArgs += '--create-database' }
        }
        Invoke-Checked $pythonPath $configurationArgs
    }
    $imported = $false
    if (Ask-YesNo 'Import the old single-workspace SQLite backup into this empty local database?' $false) {
        $sourcePath = Read-Host 'SQLite backup path without quotes (for example D:\cda backup\db.sqlite3)'
        Invoke-Checked $pythonPath @('import_sqlite_to_postgres.py', $sourcePath, '--use-saved-connection')
        if (Ask-YesNo 'Import the verified backup now? Existing target app data will be refused.' $true) {
            Invoke-Checked $pythonPath @('import_sqlite_to_postgres.py', $sourcePath, '--use-saved-connection', '--apply')
            $imported = $true
        }
    }
    Invoke-Checked $pythonPath @('manage.py', 'check_database')
    Invoke-Checked $pythonPath @('manage.py', 'migrate', '--noinput')
    Invoke-Checked $pythonPath @('manage.py', 'sync_roles')
    Invoke-Checked $pythonPath @('manage.py', 'collectstatic', '--noinput')
    & $pythonPath -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); import django; django.setup(); from diary.models import Membership; raise SystemExit(0 if Membership.objects.filter(user__is_active=True,role__in=['admin','system']).exists() else 2)"
    if ($LASTEXITCODE -eq 2) { Invoke-Checked $pythonPath @('manage.py', 'create_system_admin') }
    elseif ($LASTEXITCODE -ne 0) { throw 'Could not verify administrator accounts.' }
    elseif ($imported) { Write-Host 'Use your imported Administration administrator account and existing password.' }
    if (Ask-YesNo 'Install automatic startup?' $true) {
        if (Ask-YesNo 'Start before Windows sign-in? Requires your Windows account password; otherwise start at sign-in.' $false) { $script:StartupMode = 'Boot' }
        else { $script:StartupMode = 'Logon' }
        Install-StartupTask
    }
    if (Ask-YesNo 'Start the app now?' $true) { Start-App }
}

try {
    switch ($Action) {
        'Setup' { Setup-App }
        'Run' { Run-App }
        'Start' { Start-App }
        'Stop' { Stop-App }
        'Restart' { Stop-App; Start-App }
        'InstallTask' { Install-StartupTask }
        'RemoveTask' {
            Stop-App
            if (Get-OwnedTask) { Unregister-ScheduledTask -TaskName $TaskName -TaskPath '\' -Confirm:$false }
            Write-Host 'Automatic startup removed. Database, credentials and app files were retained.'
        }
        'Status' {
            $task = Get-OwnedTask; $process = Get-OwnedProcess
            if ($process) { Write-Host "App process running: $($process.Id)" } else { Write-Host 'App process stopped or not managed by this script.' }
            if ($task) { Write-Host "Startup task: $TaskName, state $($task.State)" } else { Write-Host 'Automatic startup is not installed.' }
            Write-Host "Logs: $runtimePath"
        }
    }
} catch {
    if ($Action -eq 'Run') {
        New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
        $_.Exception.Message | Set-Content -LiteralPath $launcherErrorPath -Encoding UTF8
    }
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
