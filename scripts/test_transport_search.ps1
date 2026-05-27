# Direct transport search/route tests (no Atlas).
# Usage: .\scripts\test_transport_search.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) { $Py = "python" }
$env:PYTHONPATH = $RepoRoot
& $Py (Join-Path $RepoRoot "scripts\test_transport_search.py")
exit $LASTEXITCODE
