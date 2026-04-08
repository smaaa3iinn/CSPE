# Starts CSPE API (:5057) + Streamlit map (:8501) + Atlas (src\work\atlas\start_atlas.bat if present).
# Pre-warms Streamlit and opens the map in your browser (unless -SkipMapBrowser) so the page is hot before you talk to Atlas.

[CmdletBinding()]
param(
    [switch]$SkipMapBrowser
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Root = $PSScriptRoot
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No .venv\Scripts\python.exe - using 'python' on PATH."
    $py = "python"
}
$streamlit = Join-Path $Root ".venv\Scripts\streamlit.exe"
if (-not (Test-Path $streamlit)) {
    $streamlit = "streamlit"
}

$AtlasRoot = Join-Path $Root "src\work\atlas"
$AtlasBat = Join-Path $AtlasRoot "start_atlas.bat"

# Inherited by Streamlit, Atlas API, wake, UI, and any cmd.exe children.
$env:CSPE_API_BASE = if ($env:CSPE_API_BASE) { $env:CSPE_API_BASE } else { "http://127.0.0.1:5057" }
$env:CSPE_STREAMLIT_URL = if ($env:CSPE_STREAMLIT_URL) { $env:CSPE_STREAMLIT_URL } else { "http://127.0.0.1:8501" }

function Wait-HttpOk {
    param(
        [string]$Url,
        [string]$Label,
        [int]$MaxSeconds = 120
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -lt 500) {
                Write-Host "  $Label ready ($Url)"
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    throw "Timeout waiting for $Label at $Url"
}

function Invoke-StreamlitWarmup {
    param([string]$MapUrl)
    Write-Host "  Pre-warming Streamlit (first load compiles the app)..."
    for ($i = 1; $i -le 2; $i++) {
        try {
            $null = Invoke-WebRequest -Uri $MapUrl -UseBasicParsing -TimeoutSec 120 -ErrorAction Stop
        }
        catch {
            Write-Warning "Warmup request $i failed (continuing): $_"
        }
        Start-Sleep -Seconds 1
    }
    Write-Host "  Streamlit warmup done."
}

Write-Host ""
Write-Host "=== CSPE + Atlas full stack ==="
Write-Host "CSPE_API_BASE       = $($env:CSPE_API_BASE)"
Write-Host "CSPE_STREAMLIT_URL  = $($env:CSPE_STREAMLIT_URL)"
Write-Host ""

Write-Host "[1/3] Starting CSPE API (minimized window)..."
Start-Process -FilePath $py -ArgumentList @("-m", "cspe_api") -WorkingDirectory $Root -WindowStyle Minimized
Wait-HttpOk -Url "http://127.0.0.1:5057/health" -Label "CSPE API"

Write-Host "[2/3] Starting Streamlit (minimized, headless - no auto browser tab)..."
$stArgs = @(
    "run", "app\app.py",
    "--server.address", "127.0.0.1",
    "--server.port", "8501",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false"
)
Start-Process -FilePath $streamlit -ArgumentList $stArgs -WorkingDirectory $Root -WindowStyle Minimized
$mapUrl = $env:CSPE_STREAMLIT_URL.TrimEnd("/")
Wait-HttpOk -Url "$mapUrl/" -Label "Streamlit"
Invoke-StreamlitWarmup -MapUrl "$mapUrl/"

if (-not $SkipMapBrowser) {
    Write-Host "  Opening map in default browser: $mapUrl"
    Start-Process $mapUrl
}

if (-not (Test-Path $AtlasBat)) {
    Write-Host ""
    Write-Warning "Atlas launcher not found: $AtlasBat"
    Write-Host "CSPE API and Streamlit are running. Start Atlas yourself from your Atlas folder,"
    Write-Host "after setting in that session: CSPE_API_BASE and CSPE_STREAMLIT_URL (see above)."
    Write-Host ""
    exit 0
}

Write-Host "[3/3] Starting Atlas (start_atlas.bat - API, wake, UI)..."
Start-Process -FilePath $AtlasBat -WorkingDirectory $AtlasRoot

Write-Host ""
Write-Host "All starters launched. Close the minimized CSPE / Streamlit consoles when you are done."
if ($SkipMapBrowser) {
    Write-Host "Map URL (open manually or ask Atlas): $mapUrl"
}
else {
    Write-Host "Map should already be open in the browser; Atlas can open it again if you ask."
}
Write-Host ""
