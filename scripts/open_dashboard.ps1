$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serverScript = Join-Path $repoRoot 'scripts\server.py'
$dashboardUrl = 'http://127.0.0.1:8765/dashboards/index.html'
$healthUrl = 'http://127.0.0.1:8765/api/health'

try {
    Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 | Out-Null
} catch {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw 'Python 3.10+ not found. Install Python or use the Windows startup setup.' }
    $pythonExe = (& $pythonCommand.Source -c 'import sys; print(sys.executable)' | Select-Object -Last 1).Trim()
    if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe)) { throw 'Could not locate the active Python interpreter.' }
    & $pythonExe -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10 or newer is required.' }

    $pythonw = Join-Path (Split-Path $pythonExe -Parent) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $pythonExe }
    Start-Process -FilePath $pythonw -ArgumentList @('"' + $serverScript + '"') -WorkingDirectory $repoRoot -WindowStyle Hidden

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1 | Out-Null
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) { throw 'The local server did not start. Check Python, .env, and whether port 8765 is available.' }
}

Start-Process $dashboardUrl
