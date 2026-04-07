$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Missing $py. Recreate the venv: run .\setup_venv.ps1 from the project folder, then try again."
}

& $py "$PSScriptRoot\launch_desktop.py"
