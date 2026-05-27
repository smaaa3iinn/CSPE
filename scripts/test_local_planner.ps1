# Run local planner tests (uses Atlas venv + correct script path).
# Usage:
#   .\scripts\test_local_planner.ps1
#   .\scripts\test_local_planner.ps1 -Benchmark

param([switch]$Benchmark)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AtlasVenvPython = Join-Path $RepoRoot "src\work\atlas\.venv\Scripts\python.exe"
$TestScript = Join-Path $RepoRoot "scripts\test_local_planner.py"

if (-not (Test-Path $AtlasVenvPython)) {
    Write-Error "Atlas venv not found: $AtlasVenvPython`nRun setup under src\work\atlas first."
}
if (-not (Test-Path $TestScript)) {
    Write-Error "Test script not found: $TestScript"
}

if (-not $env:ATLAS_PLANNER_BACKEND) {
    $env:ATLAS_PLANNER_BACKEND = "local"
}
if (-not $env:ATLAS_LOCAL_PLANNER_FALLBACK_OPENAI) {
    $env:ATLAS_LOCAL_PLANNER_FALLBACK_OPENAI = "0"
}
if (-not $env:ATLAS_LOCAL_PLANNER_TIMEOUT -or $env:ATLAS_LOCAL_PLANNER_TIMEOUT -eq "20") {
    $env:ATLAS_LOCAL_PLANNER_TIMEOUT = "60"
}
if (-not $env:ATLAS_LOCAL_PLANNER_MODEL) {
    $env:ATLAS_LOCAL_PLANNER_MODEL = "qwen2.5:3b-instruct"
}

$pyArgs = @()
if ($Benchmark) {
    $pyArgs += "--benchmark"
}

& $AtlasVenvPython $TestScript @pyArgs
