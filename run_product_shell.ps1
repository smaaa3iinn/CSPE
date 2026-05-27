# Product BFF (FastAPI): normalized APIs for the React shell. Run from repo root.
# For Atlas + Vite together, use .\run_web_app.ps1 (starts Atlas headless + this API + frontend).
# Transport map needs a Mapbox token: set MAPBOX_TOKEN (or MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN)
# in this shell, Windows env, or repo-root .env (loaded automatically if python-dotenv is installed).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root

$logDir = Join-Path $Root "logs"
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$healthLog = Join-Path $logDir "health.log"
$activityLog = Join-Path $logDir "activity.log"
foreach ($f in @($healthLog, $activityLog)) {
    try {
        if (-not (Test-Path -LiteralPath $f)) {
            New-Item -ItemType File -Path $f -Force | Out-Null
        }
        else {
            Clear-Content -LiteralPath $f -ErrorAction Stop
        }
    }
    catch {
        Write-Warning ("Log file locked (will append): {0}" -f $f)
    }
}
$env:CSPE_LOG_DIR = $logDir
$env:CSPE_HEALTH_LOG = $healthLog
$env:CSPE_ACTIVITY_LOG = $activityLog
$env:CSPE_LOG_RESET = "0"

Write-Host 'Listening on 0.0.0.0:8787 — LAN clients may use http://<this-PC-IPv4>:8787 when VITE_API_BASE is set.'
Write-Host ('Logs: health=' + $healthLog + '  activity=' + $activityLog)
& .\.venv\Scripts\python.exe -m uvicorn backend.product_shell.main:app --reload --host 0.0.0.0 --port 8787
