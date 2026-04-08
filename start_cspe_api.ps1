$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No .venv found; using 'python' on PATH."
    $py = "python"
}

Write-Host "CSPE API -> http://127.0.0.1:5057 (set CSPE_API_PORT to change). Ctrl+C to stop."
& $py -m cspe_api
