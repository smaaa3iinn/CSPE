# Live Atlas planner integration test (React path: POST /text on :5055).
#
# Usage:
#   .\scripts\test_live_planner_flow.ps1              # quick smoke (5 commands)
#   .\scripts\test_live_planner_flow.ps1 -Stress       # full stress suite
#   .\scripts\test_live_planner_flow.ps1 -IncludeFallbackTest
#   .\scripts\test_live_planner_flow.ps1 -Stress -Category 1,2,8

param(
    [switch]$Stress,
    [string[]]$Category = @(),
    [switch]$IncludeFallbackTest,
    [switch]$IncludeOptionalFallback
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Py)) {
    $Py = "python"
}

if ($Stress) {
    $args = @((Join-Path $RepoRoot "scripts\test_live_planner_stress.py"))
    foreach ($c in $Category) {
        $args += @("--category", $c)
    }
    if ($IncludeOptionalFallback -or $IncludeFallbackTest) {
        $args += "--include-optional-fallback"
    }
    Write-Host "Running full planner stress suite..."
    & $Py @args
    exit $LASTEXITCODE
}

$args = @((Join-Path $RepoRoot "scripts\test_live_planner_flow.py"))
if ($IncludeFallbackTest) {
    $args += "--include-fallback-test"
}
Write-Host "Running quick planner smoke test..."
& $Py @args
exit $LASTEXITCODE
