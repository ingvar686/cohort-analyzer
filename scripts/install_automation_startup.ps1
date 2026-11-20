$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serverScript = Join-Path $repoRoot 'scripts\server.py'
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw 'Python 3.10+ was not found. Install Python and make sure python.exe is on PATH.'
}

$pythonExe = (& $pythonCommand.Source -c 'import sys; print(sys.executable)' | Select-Object -Last 1).Trim()
if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Could not locate the active Python interpreter.'
}
& $pythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }
$pythonwCandidate = Join-Path (Split-Path $pythonExe -Parent) 'pythonw.exe'
if (Test-Path -LiteralPath $pythonwCandidate) { $pythonExe = $pythonwCandidate }

$taskName = 'Altegio Analytics local server'
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument ('"{0}"' -f $serverScript) -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 3650) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Starts the local Altegio Analytics server after this Windows user signs in.' -Force | Out-Null
Write-Host 'Startup is set. The local server will start after your next Windows sign-in.'
Write-Host 'Check it at http://127.0.0.1:8765/api/health'
Write-Host "To remove startup later: Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
