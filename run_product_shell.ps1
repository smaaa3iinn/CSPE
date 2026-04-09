# Product BFF (FastAPI): normalized APIs for the React shell. Run from repo root.
# For Atlas + Vite together, use .\run_web_app.ps1 (starts Atlas headless + this API + frontend).
# Transport map needs a Mapbox token: set MAPBOX_TOKEN (or MAPBOX_API_KEY / MAPBOX_ACCESS_TOKEN)
# in this shell, Windows env, or repo-root .env (loaded automatically if python-dotenv is installed).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONPATH = $PWD.Path
Write-Host 'Listening on 0.0.0.0:8787 — LAN clients may use http://<this-PC-IPv4>:8787 when VITE_API_BASE is set.'
& .\.venv\Scripts\python.exe -m uvicorn backend.product_shell.main:app --reload --host 0.0.0.0 --port 8787
