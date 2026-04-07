# Recreate .venv and install dependencies (use if .venv\Scripts\python.exe or pip is missing).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPath = Join-Path $PSScriptRoot ".venv"
if (Test-Path $venvPath) {
    Write-Host "Removing incomplete or old .venv ..."
    Remove-Item -Recurse -Force $venvPath
}

Write-Host "Creating virtual environment..."
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m venv .venv
} else {
    python -m venv .venv
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "venv creation failed: $py not found. Install Python 3 and ensure 'python' or 'py' is on PATH."
}

Write-Host "Upgrading pip and installing requirements..."
& $py -m pip install --upgrade pip
& $py -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "Done. Run .\run_app.ps1"
