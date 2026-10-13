$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Setup failed at: $Executable $($Arguments -join ' ')" }
}
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        $pythonCommand = Get-Command python -ErrorAction Stop
        Invoke-Checked $pythonCommand.Source @('--version')
        Invoke-Checked $pythonCommand.Source @('-m', 'venv', '.venv')
    }
    $instancePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    Invoke-Checked $instancePython @('-m', 'pip', 'install', '-r', 'requirements.txt')
    if (-not (Test-Path -LiteralPath '.instance.json') -and -not $env:DATABASE_URL) {
        Invoke-Checked $instancePython @('setup_instance.py')
    }
    Invoke-Checked $instancePython @('manage.py', 'check_database')
    Invoke-Checked $instancePython @('manage.py', 'migrate')
    Invoke-Checked $instancePython @('manage.py', 'sync_roles')
    Invoke-Checked $instancePython @('manage.py', 'collectstatic', '--noinput')
    & $instancePython -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); import django; django.setup(); from diary.models import Membership; raise SystemExit(0 if Membership.objects.filter(role='system',user__is_active=True).exists() else 2)"
    if ($LASTEXITCODE -eq 2) { Invoke-Checked $instancePython @('manage.py', 'create_system_admin') }
    elseif ($LASTEXITCODE -ne 0) { throw 'Could not check administrator account.' }
    Write-Host 'Setup complete. Start the application with start_windows.bat.'
} catch {
    Write-Error ('Setup stopped: ' + $_.Exception.Message)
    exit 1
}
