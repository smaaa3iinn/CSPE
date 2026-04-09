# Full product stack: Atlas headless (5055) + product API (8787) + Vite (5173).
# Optional: CSPE Flask API for Atlas transport tools — set $StartCspeApi or use start_cspe_api.ps1 separately.
#
# Atlas interpreter: set ATLAS_PYTHON to the python.exe that has Atlas installed (e.g. global 3.12 or Atlas .venv).
# Mapbox: MAPBOX_TOKEN in env or repo-root .env

[CmdletBinding()]
param(
    [switch]$SkipAtlas,
    [switch]$StartCspeApi
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
# Do NOT set PYTHONPATH globally: Atlas subprocesses must not inherit CSPE root or imports break.

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
                Write-Host "  $Label ready:" $Url
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
    }
    throw "Timeout waiting for $Label at $Url"
}

function Wait-AtlasHttpOk {
    param(
        [string]$Url,
        [string]$Label,
        [int]$MaxSeconds = 120,
        [System.Diagnostics.Process]$WatchProcess,
        [string]$StderrLogPath
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $nextMsg = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        if ($null -ne $WatchProcess -and $WatchProcess.HasExited) {
            $tail = Get-Content -LiteralPath $StderrLogPath -Tail 40 -ErrorAction SilentlyContinue
            $tailTxt = if ($tail) { $tail -join "`n" } else { '(empty)' }
            throw ('Atlas API process exited early (exit code ' + $WatchProcess.ExitCode + '). Stderr log: ' + $StderrLogPath + "`n" + $tailTxt)
        }
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -lt 500) {
                Write-Host "  $Label ready:" $Url
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 400
        }
        if ((Get-Date) -gt $nextMsg) {
            Write-Host '  ... still waiting for Atlas on port 5055 (/health)'
            $nextMsg = (Get-Date).AddSeconds(5)
        }
    }
    $tail2 = Get-Content -LiteralPath $StderrLogPath -Tail 40 -ErrorAction SilentlyContinue
    $tailTxt2 = if ($tail2) { $tail2 -join "`n" } else { '(empty)' }
    throw ('Timeout waiting for ' + $Label + ' at ' + $Url + '. Stderr tail from ' + $StderrLogPath + "`n" + $tailTxt2)
}

function Resolve-AtlasPython {
    param([string]$AtlasRoot)
    $explicit = @(
        $env:ATLAS_PYTHON,
        (Join-Path $AtlasRoot ".venv\Scripts\python.exe")
    ) | Where-Object { $_ -and $_.ToString().Trim() -ne "" }

    foreach ($c in $explicit) {
        if (Test-Path -LiteralPath $c) {
            return $c
        }
    }

    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
        Write-Warning ('ATLAS_PYTHON not set; using python on PATH: ' + $cmd.Source + '. Set ATLAS_PYTHON if Atlas fails to import.')
        return $cmd.Source
    }

    $cspeVenv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $cspeVenv) {
        Write-Warning 'Using CSPE .venv for Atlas - only works if Atlas packages are installed there.'
        return $cspeVenv
    }

    return $null
}

$AtlasRoot = Join-Path $Root "src\work\atlas"
$runApi = Join-Path $AtlasRoot "src\atlas_client\app\run_api.py"
$wakeMain = Join-Path $AtlasRoot "src\wake_service\main.py"

$cspePy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $cspePy)) {
    $cspePy = "python"
}

$atlasApiProc = $null
$atlasWakeProc = $null
$cspeApiProc = $null
$bff = $null
$savedPythonPath = $env:PYTHONPATH

try {
    if ($StartCspeApi) {
        $env:PYTHONPATH = $Root
        Write-Host '[1a] Starting CSPE API on port 5057 (minimized window)...'
        $cspeApiProc = Start-Process -FilePath $cspePy -ArgumentList @("-m", "cspe_api") `
            -WorkingDirectory $Root -WindowStyle Minimized -PassThru
        Wait-HttpOk -Url "http://127.0.0.1:5057/health" -Label "CSPE API" -MaxSeconds 90
    }

    if (-not $SkipAtlas) {
        if (-not ((Test-Path -LiteralPath $runApi) -and (Test-Path -LiteralPath $wakeMain))) {
            Write-Warning 'Atlas sources not found: expected run_api.py and wake_service. Chat will fail until Atlas runs on 5055.'
        }
        else {
            $atlasPy = Resolve-AtlasPython -AtlasRoot $AtlasRoot
            if (-not $atlasPy) {
                throw 'Could not find python.exe for Atlas. Set ATLAS_PYTHON to your interpreter (see start_atlas.bat), or add src\work\atlas\.venv'
            }
            Write-Host '[1] Starting Atlas headless (API + Wake, no UI) using:' $atlasPy
            $logDir = Join-Path $AtlasRoot "logs"
            if (-not (Test-Path -LiteralPath $logDir)) {
                New-Item -ItemType Directory -Path $logDir | Out-Null
            }
            $apiLog = Join-Path $logDir "api.log"
            $apiErr = Join-Path $logDir "api.err.log"
            $wakeLog = Join-Path $logDir "wake.log"
            $wakeErr = Join-Path $logDir "wake.err.log"
            foreach ($f in @($apiLog, $apiErr, $wakeLog, $wakeErr)) {
                "" | Set-Content -LiteralPath $f -Encoding utf8
            }

            # Atlas must see its own tree first; CSPE PYTHONPATH breaks `python -m src.atlas_client...`.
            $env:PYTHONPATH = $AtlasRoot
            Write-Host '  PYTHONPATH for Atlas:' $AtlasRoot

            $atlasApiProc = Start-Process -FilePath $atlasPy `
                -ArgumentList @("-m", "src.atlas_client.app.run_api") `
                -WorkingDirectory $AtlasRoot -WindowStyle Hidden `
                -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr -PassThru

            Start-Sleep -Seconds 2

            $atlasWakeProc = Start-Process -FilePath $atlasPy `
                -ArgumentList @( (Join-Path $AtlasRoot "src\wake_service\main.py") ) `
                -WorkingDirectory $AtlasRoot -WindowStyle Hidden `
                -RedirectStandardOutput $wakeLog -RedirectStandardError $wakeErr -PassThru

            Wait-AtlasHttpOk -Url "http://127.0.0.1:5055/health" -Label "Atlas API" -MaxSeconds 120 `
                -WatchProcess $atlasApiProc -StderrLogPath $apiErr
        }
    }
    else {
        Write-Host '[1] Skipping Atlas -SkipAtlas. Ensure something serves http://127.0.0.1:5055 for chat.'
    }

    # Product BFF imports backend.* from CSPE root
    $env:PYTHONPATH = $Root

    # Defaults for Atlas CSPE tools (optional)
    if (-not $env:CSPE_API_BASE) { $env:CSPE_API_BASE = "http://127.0.0.1:5057" }
    if (-not $env:CSPE_STREAMLIT_URL) { $env:CSPE_STREAMLIT_URL = "http://127.0.0.1:5173" }

    Write-Host '[2] Starting product API on port 8787 (minimized window)...'
    $bff = Start-Process -FilePath $cspePy -ArgumentList @(
        "-m", "uvicorn", "backend.product_shell.main:app", "--reload", "--host", "0.0.0.0", "--port", "8787"
    ) -WorkingDirectory $Root -WindowStyle Minimized -PassThru

    Start-Sleep -Seconds 2
    Wait-HttpOk -Url "http://127.0.0.1:8787/api/health" -Label "Product API" -MaxSeconds 60

    Write-Host '[3] Starting Vite on 0.0.0.0:5173 - laptop: http://127.0.0.1:5173'
    Write-Host '    Same WiFi iPad or phone: http://YOUR_LAN_IP:5173 - run ipconfig to find IPv4'
    Write-Host '    Optional .env: VITE_API_BASE=http://YOUR_LAN_IP:8787 if you bypass the Vite proxy; SPOTIFY_REDIRECT_URI must match the page origin for OAuth.'
    Write-Host '    Spotify dashboard: add redirect URI for each origin, e.g. http://192.168.x.x:5173/callback'
    Write-Host '    Press Ctrl+C here to stop the dev server; background Python processes will be stopped.'
    Set-Location (Join-Path $Root "frontend")
    npm run dev
}
finally {
    $env:PYTHONPATH = $savedPythonPath
    Set-Location $Root
    if ($bff -and -not $bff.HasExited) {
        Stop-Process -Id $bff.Id -Force -ErrorAction SilentlyContinue
    }
    if ($cspeApiProc -and -not $cspeApiProc.HasExited) {
        Stop-Process -Id $cspeApiProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($atlasWakeProc -and -not $atlasWakeProc.HasExited) {
        Stop-Process -Id $atlasWakeProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($atlasApiProc -and -not $atlasApiProc.HasExited) {
        Stop-Process -Id $atlasApiProc.Id -Force -ErrorAction SilentlyContinue
    }
}
