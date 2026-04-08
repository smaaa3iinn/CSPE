# Starts product API (8787) and Vite dev server (5173). Requires Atlas on 5055 for chat.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONPATH = $PWD.Path

$api = Start-Process -FilePath ".\.venv\Scripts\python.exe" `
  -ArgumentList @("-m", "uvicorn", "backend.product_shell.main:app", "--reload", "--host", "127.0.0.1", "--port", "8787") `
  -PassThru -WindowStyle Minimized

Start-Sleep -Seconds 2
Set-Location .\frontend
npm run dev

# If npm exits, stop API
if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
