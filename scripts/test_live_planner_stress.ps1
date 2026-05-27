# Live Atlas planner stress test — full limits suite via POST /text (:5055).
# Prerequisites: run_web_app.ps1 (Atlas + product shell), Ollama for local planner.
#
# Usage:
#   .\scripts\test_live_planner_stress.ps1
#   .\scripts\test_live_planner_stress.ps1 -Category 1,3,8
#   .\scripts\test_live_planner_stress.ps1 -IncludeOptionalFallback

param(
    [string[]]$Category = @(),
    [switch]$IncludeOptionalFallback
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    $Py = "python"
}

$args = @(
    (Join-Path $RepoRoot "scripts\test_live_planner_stress.py")
)
foreach ($c in $Category) {
    $args += @("--category", $c)
}
if ($IncludeOptionalFallback) {
    $args += "--include-optional-fallback"
}

Write-Host "Running planner stress suite..."
& $Py @args
exit $LASTEXITCODE
