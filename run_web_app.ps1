# Full product stack: Atlas headless (5055) + product API (8787) + GraphXR/WebXR (3000) + Vite (5173).
# Transport + shell + Spotify + memory APIs for the React app and Atlas tools are on the same FastAPI process (8787): /api/transport/*, /api/shell/*, etc.
# Atlas tools: CSPE_FRONTEND_URL defaults to http://127.0.0.1:5173 (React/Vite origin for cspe_open_transport_map).
# GraphXR 3D/VR viewer: http://127.0.0.1:3000/viewer (auto-started; override with VITE_GRAPHXR_VIEWER_URL).
#
# Atlas interpreter: set ATLAS_PYTHON to the python.exe that has Atlas installed (e.g. global 3.12 or Atlas .venv).
# Mapbox: MAPBOX_TOKEN in env or repo-root .env

[CmdletBinding()]
param(
    [switch]$SkipAtlas,
    [switch]$SkipGraphXR
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
        [string]$ActivityLogPath
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $nextMsg = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        if ($null -ne $WatchProcess -and $WatchProcess.HasExited) {
            $tail = Get-Content -LiteralPath $ActivityLogPath -Tail 40 -ErrorAction SilentlyContinue
            $tailTxt = if ($tail) { $tail -join "`n" } else { '(empty)' }
            throw ('Atlas API process exited early (exit code ' + $WatchProcess.ExitCode + '). Activity log tail: ' + $ActivityLogPath + "`n" + $tailTxt)
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
    $tail2 = Get-Content -LiteralPath $ActivityLogPath -Tail 40 -ErrorAction SilentlyContinue
    $tailTxt2 = if ($tail2) { $tail2 -join "`n" } else { '(empty)' }
    throw ('Timeout waiting for ' + $Label + ' at ' + $Url + '. Activity log tail from ' + $ActivityLogPath + "`n" + $tailTxt2)
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

function Stop-StaleAtlasProcesses {
    param([string]$AtlasRoot)

    $stopped = 0
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:5055/shutdown" -Method POST `
            -ContentType "application/json" -Body '{"intent":"shutdown"}' `
            -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue | Out-Null
        Start-Sleep -Milliseconds 800
    }
    catch {
        # Atlas not running or shutdown route unavailable
    }

    $patterns = @(
        'atlas_client\.app\.run_api',
        'wake_service\\main\.py',
        'wake_service/main\.py'
    )
    try {
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $cmd = $_.CommandLine
                if (-not $cmd) { return $false }
                foreach ($p in $patterns) {
                    if ($cmd -match $p) { return $true }
                }
                return $false
            } |
            ForEach-Object {
                Write-Host "  Stopping stale Atlas process PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
    }
    catch {
        Write-Warning "Could not enumerate python processes for Atlas cleanup: $_"
    }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 600
    }
}

function Stop-StaleProductShellProcesses {
    $stopped = 0

    function Stop-PidsOnPort8787 {
        param([string]$Source, [ref]$Count)
        $pids = @()
        try {
            $pids += @(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique)
        }
        catch { }

        if ($pids.Count -eq 0) {
            try {
                $lines = netstat -ano -p tcp | Select-String ':8787' | Select-String 'LISTENING'
                foreach ($line in $lines) {
                    $parts = ($line -replace '\s+', ' ').Trim().Split(' ')
                    $procId = [int]$parts[-1]
                    if ($procId -gt 0) { $pids += $procId }
                }
            }
            catch { }
        }

        foreach ($procId in ($pids | Select-Object -Unique)) {
            if ($procId -le 0) { continue }
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            $label = if ($proc -and $proc.CommandLine) { $proc.CommandLine } else { "pid=$procId" }
            Write-Host "  Stopping product API listener on :8787 ($Source) PID $procId"
            Write-Host "    $label"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $Count.Value++
        }
    }

    Stop-PidsOnPort8787 -Source 'port' -Count ([ref]$stopped)

    try {
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $cmd = $_.CommandLine
                $cmd -and ($cmd -like '*uvicorn*product_shell*')
            } |
            ForEach-Object {
                Write-Host "  Stopping stale uvicorn product_shell PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
    }
    catch {
        Write-Warning "Could not enumerate uvicorn processes: $_"
    }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 1200
    }

    # Ensure the port is actually free before starting a new listener.
    $freeDeadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $freeDeadline) {
        $stillListening = $false
        try {
            $stillListening = @(Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue).Count -gt 0
        }
        catch {
            $stillListening = $false
        }
        if (-not $stillListening) { return }
        Stop-PidsOnPort8787 -Source 'port-retry' -Count ([ref]$stopped)
        Start-Sleep -Milliseconds 600
    }

    Write-Warning 'Port 8787 still has a listener after cleanup; new product API may fail to bind.'
}

function Stop-StaleGraphXRProcesses {
    param([int]$Port = 3000)

    $stopped = 0

    function Stop-PidsOnPort {
        param([string]$Source, [ref]$Count)
        $pids = @()
        try {
            $pids += @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty OwningProcess -Unique)
        }
        catch { }

        if ($pids.Count -eq 0) {
            try {
                $lines = netstat -ano -p tcp | Select-String (":$Port\s") | Select-String 'LISTENING'
                foreach ($line in $lines) {
                    $parts = ($line -replace '\s+', ' ').Trim().Split(' ')
                    $procId = [int]$parts[-1]
                    if ($procId -gt 0) { $pids += $procId }
                }
            }
            catch { }
        }

        foreach ($procId in ($pids | Select-Object -Unique)) {
            if ($procId -le 0) { continue }
            $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
            $label = if ($proc -and $proc.CommandLine) { $proc.CommandLine } else { "pid=$procId" }
            Write-Host "  Stopping GraphXR listener on :$Port ($Source) PID $procId"
            Write-Host "    $label"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $Count.Value++
        }
    }

    Stop-PidsOnPort -Source 'port' -Count ([ref]$stopped)

    try {
        Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
            Where-Object {
                $cmd = $_.CommandLine
                $cmd -and (
                    ($cmd -like '*viewers\graphxr*') -or
                    ($cmd -like '*viewers/graphxr*') -or
                    (($cmd -like '*next*dev*') -and ($cmd -like "*:$Port*"))
                )
            } |
            ForEach-Object {
                Write-Host "  Stopping stale GraphXR node PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
    }
    catch {
        Write-Warning "Could not enumerate node processes for GraphXR cleanup: $_"
    }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 1200
    }
}

function Start-GraphXRProcess {
    param(
        [string]$ViewerDir,
        [int]$Port = 3000,
        [System.Diagnostics.Process]$Existing = $null
    )

    Stop-StaleGraphXRProcesses -Port $Port
    if ($null -ne $Existing -and -not $Existing.HasExited) {
        Stop-Process -Id $Existing.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }

    if (-not (Test-Path -LiteralPath (Join-Path $ViewerDir 'node_modules\next'))) {
        Write-Host '    GraphXR dependencies missing; running npm install in viewers\graphxr...'
        Push-Location $ViewerDir
        try {
            npm install
        }
        finally {
            Pop-Location
        }
    }

    return Start-Process -FilePath 'npm.cmd' -ArgumentList @(
        'run', 'dev', '--', '-p', "$Port", '-H', '0.0.0.0'
    ) -WorkingDirectory $ViewerDir -WindowStyle Minimized -PassThru
}

function Start-ProductShellProcess {
    param(
        [string]$PythonExe,
        [string]$WorkDir,
        [System.Diagnostics.Process]$Existing = $null
    )
    Stop-StaleProductShellProcesses
    if ($null -ne $Existing -and -not $Existing.HasExited) {
        Stop-Process -Id $Existing.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 500
    }
    return Start-Process -FilePath $PythonExe -ArgumentList @(
        "-m", "uvicorn", "backend.product_shell.main:app", "--host", "0.0.0.0", "--port", "8787"
    ) -WorkingDirectory $WorkDir -WindowStyle Minimized -PassThru
}

function Wait-ProductShellReady {
    param(
        [string]$BaseUrl = "http://127.0.0.1:8787",
        [int]$MaxSeconds = 90,
        [scriptblock]$Restart = $null
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $restartAttempts = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5 -ErrorAction Stop
            $hasExplore = $false
            if ($health.capabilities -and $health.capabilities.PSObject.Properties['transport_exploration']) {
                $hasExplore = [bool]$health.capabilities.transport_exploration
            }
            if ($health.ok -and $hasExplore) {
                Write-Host "  Product API ready (transport exploration routes):" $BaseUrl
                return
            }
            if ($health.ok -and -not $hasExplore -and $Restart -and $restartAttempts -lt 4) {
                $restartAttempts++
                Write-Host ('  Old product API still on :8787 - restarting product shell (attempt ' + $restartAttempts + ')...')
                & $Restart
                Start-Sleep -Seconds 3
                continue
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
            continue
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Timeout waiting for product API with transport exploration at $BaseUrl (stale uvicorn may still own port 8787)."
}

function Initialize-ProjectLogFiles {
    param([string]$LogDir)

    $healthLog = Join-Path $LogDir "health.log"
    $activityLog = Join-Path $LogDir "activity.log"
    $compactLog = Join-Path $LogDir "activity_compact.log"
    if (-not (Test-Path -LiteralPath $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    foreach ($f in @($healthLog, $activityLog, $compactLog)) {
        try {
            if (-not (Test-Path -LiteralPath $f)) {
                New-Item -ItemType File -Path $f -Force | Out-Null
                continue
            }
            Clear-Content -LiteralPath $f -ErrorAction Stop
        }
        catch {
            Write-Warning ("Log file locked (will append): {0} - {1}" -f $f, $_)
        }
    }
    return @{ Health = $healthLog; Activity = $activityLog; Compact = $compactLog }
}

$AtlasRoot = Join-Path $Root "src\work\atlas"
$runApi = Join-Path $AtlasRoot "src\atlas_client\app\run_api.py"
$wakeMain = Join-Path $AtlasRoot "src\wake_service\main.py"

$cspePy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $cspePy)) {
    $cspePy = "python"
}

$projectLogDir = Join-Path $Root "logs"
$projectLogs = Initialize-ProjectLogFiles -LogDir $projectLogDir

function Import-RepoDotEnv {
    param([string]$EnvPath)
    if (-not (Test-Path -LiteralPath $EnvPath)) { return }
    Get-Content -LiteralPath $EnvPath | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $name = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if ($name) { Set-Item -Path "env:$name" -Value $value -Force }
    }
}
Import-RepoDotEnv (Join-Path $Root ".env")
if ($env:ATLAS_PLANNER_BACKEND) {
    Write-Host 'Planner backend:' $env:ATLAS_PLANNER_BACKEND
} else {
    Write-Host 'Planner backend: openai (default)'
}

$env:CSPE_LOG_DIR = $projectLogDir
$env:CSPE_HEALTH_LOG = $projectLogs.Health
$env:CSPE_ACTIVITY_LOG = $projectLogs.Activity
$env:CSPE_COMPACT_LOG = $projectLogs.Compact
if (-not $env:CSPE_LOG_MODE) { $env:CSPE_LOG_MODE = "compact" }
$env:CSPE_LOG_RESET = "0"
Write-Host 'Project logs (reset each run):'
Write-Host ('  health:   ' + $projectLogs.Health)
Write-Host ('  activity: ' + $projectLogs.Activity)
Write-Host ('  compact:  ' + $projectLogs.Compact)
Write-Host ('  mode:     ' + $env:CSPE_LOG_MODE)

$atlasApiProc = $null
$atlasWakeProc = $null
$bff = $null
$graphxrProc = $null
$savedPythonPath = $env:PYTHONPATH
$graphxrPort = 3000
if ($env:GRAPHXR_PORT -and $env:GRAPHXR_PORT.Trim() -match '^\d+$') {
    $graphxrPort = [int]$env:GRAPHXR_PORT
}
$graphxrDir = Join-Path $Root 'viewers\graphxr'
$graphxrViewerUrl = "http://127.0.0.1:$graphxrPort/viewer"

try {
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
            Stop-StaleAtlasProcesses -AtlasRoot $AtlasRoot

            # Atlas must see its own tree first; CSPE PYTHONPATH breaks `python -m src.atlas_client...`.
            $env:PYTHONPATH = $AtlasRoot
            Write-Host '  PYTHONPATH for Atlas:' $AtlasRoot

            $atlasApiProc = Start-Process -FilePath $atlasPy `
                -ArgumentList @("-m", "src.atlas_client.app.run_api") `
                -WorkingDirectory $AtlasRoot -WindowStyle Hidden -PassThru

            Start-Sleep -Seconds 2

            $atlasWakeProc = Start-Process -FilePath $atlasPy `
                -ArgumentList @( (Join-Path $AtlasRoot "src\wake_service\main.py") ) `
                -WorkingDirectory $AtlasRoot -WindowStyle Hidden -PassThru

            Wait-AtlasHttpOk -Url "http://127.0.0.1:5055/health" -Label "Atlas API" -MaxSeconds 120 `
                -WatchProcess $atlasApiProc -ActivityLogPath $projectLogs.Activity
        }
    }
    else {
        Write-Host '[1] Skipping Atlas -SkipAtlas. Ensure something serves http://127.0.0.1:5055 for chat.'
    }

    # Product BFF imports backend.* from CSPE root
    $env:PYTHONPATH = $Root

    # Defaults for Atlas tools: PRODUCT_SHELL_URL = FastAPI (graph /v1 + /api); CSPE_FRONTEND_URL = Vite origin.
    if (-not $env:PRODUCT_SHELL_URL) { $env:PRODUCT_SHELL_URL = "http://127.0.0.1:8787" }
    # Atlas tools (e.g. cspe_open_transport_map): origin of the React/Vite app (not the API port).
    if (-not $env:CSPE_FRONTEND_URL) { $env:CSPE_FRONTEND_URL = "http://127.0.0.1:5173" }

    Write-Host '[2] Starting product API on port 8787 (minimized window)...'
    & (Join-Path $Root 'stop_product_shell.ps1')
    $bff = Start-ProductShellProcess -PythonExe $cspePy -WorkDir $Root
    Wait-ProductShellReady -BaseUrl "http://127.0.0.1:8787" -MaxSeconds 90 -Restart {
        $bff = Start-ProductShellProcess -PythonExe $cspePy -WorkDir $Root -Existing $bff
    }.GetNewClosure()

    if (-not $SkipGraphXR) {
        if (-not (Test-Path -LiteralPath (Join-Path $graphxrDir 'package.json'))) {
            Write-Warning 'GraphXR viewer not found at viewers\graphxr — skipping 3D/VR dev server.'
        }
        else {
            Write-Host "[3] Starting GraphXR WebXR viewer on 0.0.0.0:$graphxrPort (minimized window)..."
            $graphxrProc = Start-GraphXRProcess -ViewerDir $graphxrDir -Port $graphxrPort
            Wait-HttpOk -Url $graphxrViewerUrl -Label 'GraphXR viewer' -MaxSeconds 120
            if (-not $env:VITE_GRAPHXR_VIEWER_URL) {
                $env:VITE_GRAPHXR_VIEWER_URL = $graphxrViewerUrl
            }
            Write-Host '    3D/VR graph opens from Transport mode -> 3D/VR graph button'
        }
    }
    else {
        Write-Host '[3] Skipping GraphXR -SkipGraphXR. Set VITE_GRAPHXR_VIEWER_URL if the viewer runs elsewhere.'
        if (-not $env:VITE_GRAPHXR_VIEWER_URL) {
            $env:VITE_GRAPHXR_VIEWER_URL = $graphxrViewerUrl
        }
    }

    Write-Host '[4] Starting Vite on 0.0.0.0:5173 - laptop: http://127.0.0.1:5173'
    Write-Host '    Same WiFi iPad or phone: http://YOUR_LAN_IP:5173 - run ipconfig to find IPv4'
    Write-Host '    GraphXR viewer:' $env:VITE_GRAPHXR_VIEWER_URL
    Write-Host '    Optional .env: VITE_API_BASE=http://YOUR_LAN_IP:8787 if you bypass the Vite proxy; SPOTIFY_REDIRECT_URI must match the page origin for OAuth.'
    Write-Host '    Spotify dashboard: add redirect URI for each origin, e.g. http://192.168.x.x:5173/callback'
    Write-Host '    Logs: Get-Content logs\activity_compact.log -Wait  (readable)  |  logs\activity.log  (full)  |  logs\health.log'
    Write-Host '    Press Ctrl+C here to stop the dev server; background Python/Node processes will be stopped.'
    $frontendDir = Join-Path $Root "frontend"
    Set-Location $frontendDir
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules\vite'))) {
        Write-Host '    Frontend dependencies missing; running npm install in frontend...'
        npm install
    }
    npm run dev
}
finally {
    $env:PYTHONPATH = $savedPythonPath
    Set-Location $Root
    if ($graphxrProc -and -not $graphxrProc.HasExited) {
        Stop-Process -Id $graphxrProc.Id -Force -ErrorAction SilentlyContinue
    }
    if (-not $SkipGraphXR) {
        Stop-StaleGraphXRProcesses -Port $graphxrPort
    }
    if ($bff -and -not $bff.HasExited) {
        Stop-Process -Id $bff.Id -Force -ErrorAction SilentlyContinue
    }
    if ($atlasWakeProc -and -not $atlasWakeProc.HasExited) {
        Stop-Process -Id $atlasWakeProc.Id -Force -ErrorAction SilentlyContinue
    }
    if ($atlasApiProc -and -not $atlasApiProc.HasExited) {
        Stop-Process -Id $atlasApiProc.Id -Force -ErrorAction SilentlyContinue
    }
}
