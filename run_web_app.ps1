# Full product stack: Atlas headless (5055) + product API (8787) + GraphXR/WebXR (3000) + Vite (5173).
# Transport + shell APIs for the React app and Atlas tools are on the same FastAPI process (8787): /api/transport/*, /api/shell/*, etc.
# Atlas tools: CSPE_FRONTEND_URL defaults to http://127.0.0.1:5173 (React/Vite origin for cspe_open_transport_map).
# GraphXR 3D/VR viewer: http://127.0.0.1:3000/viewer (auto-started; override with VITE_GRAPHXR_VIEWER_URL).
# Meta Quest WebXR (optional): .\run_web_app.ps1 -QuestVR
#   Starts proxy-vr.js on :8080 + ngrok tunnel for a single HTTPS URL (required for Quest browser WebXR).
#
# Atlas interpreter: set ATLAS_PYTHON to the python.exe that has Atlas installed (e.g. global 3.12 or Atlas .venv).
# Mapbox: MAPBOX_TOKEN in env or repo-root .env

[CmdletBinding()]
param(
    [switch]$SkipAtlas,
    [switch]$SkipGraphXR,
    [switch]$QuestVR
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
    $patterns = @(
        'atlas_client\.app\.run_api'
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

function Get-LanIPv4Address {
    try {
        $candidate = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and
                $_.PrefixOrigin -ne 'WellKnown'
            } |
            Sort-Object InterfaceMetric |
            Select-Object -First 1 -ExpandProperty IPAddress
        if ($candidate) { return $candidate }
    }
    catch { }

    try {
        $lines = ipconfig | Select-String -Pattern 'IPv4 Address[\.\s]*:\s*(\d+\.\d+\.\d+\.\d+)'
        foreach ($line in $lines) {
            if ($line.Line -match '(\d+\.\d+\.\d+\.\d+)') {
                $ip = $Matches[1]
                if ($ip -notmatch '^(127\.|169\.254\.)') { return $ip }
            }
        }
    }
    catch { }

    return $null
}

function Test-PortListening {
    param([int]$Port)

    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
    }
    catch { }

    try {
        $pattern = (":$Port\s")
        return @(netstat -ano -p tcp | Select-String $pattern | Select-String 'LISTENING').Count -gt 0
    }
    catch { }

    return $false
}

function Wait-PortListening {
    param(
        [int]$Port,
        [string]$Label,
        [int]$MaxSeconds = 45
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening -Port $Port) {
            Write-Host "  $Label listening on port $Port"
            return
        }
        Start-Sleep -Milliseconds 400
    }
    throw "Timeout waiting for $Label to listen on port $Port"
}

function Stop-StaleVrProxyProcesses {
    param([int]$Port = 8080)

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
            Write-Host "  Stopping VR proxy listener on :$Port ($Source) PID $procId"
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
                $cmd -and ($cmd -like '*proxy-vr.js*')
            } |
            ForEach-Object {
                Write-Host "  Stopping stale proxy-vr.js node PID $($_.ProcessId)"
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                $stopped++
            }
    }
    catch {
        Write-Warning "Could not enumerate node processes for VR proxy cleanup: $_"
    }

    if ($stopped -gt 0) {
        Start-Sleep -Milliseconds 800
    }
}

function Resolve-NgrokCommand {
    $cmd = Get-Command ngrok.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    $cmd = Get-Command ngrok -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    return $null
}

function Start-QuestVrProxyProcess {
    param(
        [string]$WorkDir,
        [int]$Port = 8080
    )

    $proxyScript = Join-Path $WorkDir 'proxy-vr.js'
    if (-not (Test-Path -LiteralPath $proxyScript)) {
        throw "Quest VR proxy not found: $proxyScript"
    }

    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) {
        throw 'node.exe not found on PATH. Install Node.js to run proxy-vr.js.'
    }

    $proxyModules = Join-Path $WorkDir 'node_modules\http-proxy'
    if (-not (Test-Path -LiteralPath $proxyModules)) {
        Write-Host '    VR proxy dependency missing; running npm install in repo root...'
        Push-Location $WorkDir
        try {
            npm install
        }
        finally {
            Pop-Location
        }
    }

    Stop-StaleVrProxyProcesses -Port $Port
    if (Test-PortListening -Port $Port) {
        throw "Port $Port is still in use after cleanup. Stop the process using it, then retry -QuestVR."
    }

    $escapedRoot = $WorkDir.Replace("'", "''")
    $psCommand = @"
Set-Location -LiteralPath '$escapedRoot'
Write-Host 'CSPE Quest VR reverse proxy on http://0.0.0.0:$Port'
Write-Host '  /      -> Vite :5173'
Write-Host '  /viewer -> GraphXR :3000'
Write-Host '  /api   -> Product API :8787'
node proxy-vr.js
"@

    return Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-Command',
        $psCommand
    ) -PassThru
}

function Start-QuestVrNgrokProcess {
    param([int]$Port = 8080)

    $ngrokExe = Resolve-NgrokCommand
    if (-not $ngrokExe) {
        Write-Host ''
        Write-Host 'ERROR: ngrok was not found on PATH.' -ForegroundColor Red
        Write-Host '  Install from https://ngrok.com/download'
        Write-Host '  Authenticate once: ngrok config add-authtoken <your-token>'
        Write-Host '  Docs: https://ngrok.com/docs/getting-started'
        return $null
    }

    $escapedNgrok = $ngrokExe.Replace("'", "''")
    $psCommand = @"
Write-Host 'CSPE Quest VR ngrok tunnel -> http://127.0.0.1:$Port'
Write-Host 'Copy the https://... forwarding URL into the Meta Quest browser.'
& '$escapedNgrok' http http://127.0.0.1:$Port
"@

    return Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-NoExit',
        '-Command',
        $psCommand
    ) -PassThru
}

function Get-NgrokHttpsUrlForPort {
    param([int]$Port = 8080)

    try {
        $resp = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3 -ErrorAction Stop
        $tunnels = @($resp.tunnels)
        if ($tunnels.Count -eq 0) {
            return $null
        }
        $portSuffix = ":$Port"
        $https = @($tunnels | Where-Object {
                $_.public_url -like 'https://*' -and (
                    ($_.config.addr -like "*$portSuffix") -or
                    ($_.config.addr -eq "http://127.0.0.1:$Port") -or
                    ($_.config.addr -eq "http://localhost:$Port")
                )
            } | Select-Object -First 1).public_url
        if (-not $https) {
            $https = @($tunnels | Where-Object { $_.public_url -like 'https://*' } | Select-Object -First 1).public_url
        }
        if (-not $https) {
            $https = $tunnels[0].public_url
        }
        if ($https) {
            return ($https -replace '/$', '')
        }
    }
    catch {
        return $null
    }
    return $null
}

function Get-NgrokHttpsUrl {
    param([int]$MaxSeconds = 45, [int]$Port = 8080)

    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    while ((Get-Date) -lt $deadline) {
        $https = Get-NgrokHttpsUrlForPort -Port $Port
        if ($https) {
            return $https
        }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Write-QuestVrInstructions {
    param(
        [string]$QuestHttpsUrl,
        [string]$LanIp,
        [int]$ProxyPort = 8080
    )

    Write-Host ''
    Write-Host '========== Meta Quest 3 (WebXR) ==========' -ForegroundColor Cyan
    Write-Host '  WebXR on Quest requires HTTPS (ngrok). Plain http:// LAN URLs will not enter VR.'
    Write-Host '  Local app (PC):  http://127.0.0.1:5173'
    if ($LanIp) {
        Write-Host ("  LAN app (PC):    http://${LanIp}:5173  (no WebXR on Quest over HTTP)")
    }
    else {
        Write-Host '  LAN app (PC):    http://<your-wifi-ip>:5173  (run ipconfig to find IPv4)'
    }
    Write-Host ("  VR proxy:        http://127.0.0.1:${ProxyPort}")
    if ($QuestHttpsUrl) {
        Write-Host ("  Quest HTTPS:     $QuestHttpsUrl") -ForegroundColor Green
        Write-Host ("  GraphXR viewer:  $QuestHttpsUrl/viewer")
        Write-Host ''
        Write-Host '  On Quest: open Quest HTTPS URL -> Transport -> 3D/VR graph -> VR -> Enter VR'
        Write-Host ''
        Write-Host '  Vite env for this run (also set in .env if you restart Vite alone):'
        Write-Host ("    VITE_API_BASE=$QuestHttpsUrl")
        Write-Host ("    VITE_GRAPHXR_VIEWER_URL=$QuestHttpsUrl/viewer")
        Write-Host ''
        Write-Host '  Note: free ngrok URLs change each run. Do not commit old URLs to .env.'
    }
    else {
        Write-Host '  Quest HTTPS:     (read https://... from the ngrok window; API poll timed out)'
        Write-Host '  After you have the URL, set in .env before restarting Vite if needed:'
        Write-Host '    VITE_API_BASE=https://<ngrok-host>'
        Write-Host '    VITE_GRAPHXR_VIEWER_URL=https://<ngrok-host>/viewer'
    }
    Write-Host '=========================================='
    Write-Host ''
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

function Wait-ProductShellWarm {
    param(
        [string]$BaseUrl = "http://127.0.0.1:8787",
        [int]$MaxSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    $nextMsg = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5 -ErrorAction Stop
            if ($health.warmup -and $health.warmup.complete) {
                $ok = [bool]$health.warmup.ok
                $elapsed = $health.warmup.elapsed_ms
                Write-Host ("  Product warmup complete ok={0} elapsed_ms={1}" -f $ok, $elapsed)
                return
            }
            if ($health.warmup -and $health.warmup.running -and (Get-Date) -gt $nextMsg) {
                $steps = @($health.warmup.steps).Count
                Write-Host ("  ... product warmup running ({0} steps done)" -f $steps)
                $nextMsg = (Get-Date).AddSeconds(5)
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
            continue
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Warning "Product warmup did not finish within $MaxSeconds seconds; continuing with background warmup."
}

function Warm-AtlasTextSession {
    param(
        [string]$BaseUrl = "http://127.0.0.1:8787"
    )
    try {
        Write-Host "  Warming Atlas text session via product shell..."
        Invoke-RestMethod -Uri "$BaseUrl/api/atlas/input-mode" `
            -Method Post `
            -ContentType "application/json" `
            -Body '{"mode":"text"}' `
            -TimeoutSec 60 `
            -ErrorAction Stop | Out-Null
        Write-Host "  Atlas text session warm."
    }
    catch {
        Write-Warning ("Atlas text warmup failed; first chat may still start Atlas: " + $_)
    }
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
$bff = $null
$graphxrProc = $null
$vrProxyProc = $null
$ngrokProc = $null
$questVrHttpsUrl = $null
$lanIp = $null
$vrProxyPort = 8080
$savedPythonPath = $env:PYTHONPATH
$graphxrPort = 3000
if ($env:GRAPHXR_PORT -and $env:GRAPHXR_PORT.Trim() -match '^\d+$') {
    $graphxrPort = [int]$env:GRAPHXR_PORT
}
$graphxrDir = Join-Path $Root 'viewers\graphxr'
$graphxrViewerUrl = "http://127.0.0.1:$graphxrPort/viewer"

try {
    if (-not $SkipAtlas) {
        if (-not (Test-Path -LiteralPath $runApi)) {
            Write-Warning 'Atlas sources not found: expected run_api.py. Chat will fail until Atlas runs on 5055.'
        }
        else {
            $atlasPy = Resolve-AtlasPython -AtlasRoot $AtlasRoot
            if (-not $atlasPy) {
                throw 'Could not find python.exe for Atlas. Set ATLAS_PYTHON to your interpreter (see start_atlas.bat), or add src\work\atlas\.venv'
            }
            Write-Host '[1] Starting Atlas headless (API only, no UI) using:' $atlasPy
            Stop-StaleAtlasProcesses -AtlasRoot $AtlasRoot

            # Atlas must see its own tree first; CSPE PYTHONPATH breaks `python -m src.atlas_client...`.
            $env:PYTHONPATH = $AtlasRoot
            Write-Host '  PYTHONPATH for Atlas:' $AtlasRoot

            $atlasApiProc = Start-Process -FilePath $atlasPy `
                -ArgumentList @("-m", "src.atlas_client.app.run_api") `
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
    if (-not $SkipAtlas) {
        Warm-AtlasTextSession -BaseUrl "http://127.0.0.1:8787"
    }
    Wait-ProductShellWarm -BaseUrl "http://127.0.0.1:8787" -MaxSeconds 60

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

    $lanIp = Get-LanIPv4Address

    if ($QuestVR) {
        Write-Host '[Quest VR] Starting HTTPS reverse proxy + ngrok for Meta Quest WebXR...'
        try {
            $vrProxyProc = Start-QuestVrProxyProcess -WorkDir $Root -Port $vrProxyPort
            Wait-PortListening -Port $vrProxyPort -Label 'Quest VR proxy' -MaxSeconds 45
            Wait-HttpOk -Url "http://127.0.0.1:$vrProxyPort/health" -Label 'Quest VR proxy health' -MaxSeconds 15
            Write-Host "  VR proxy ready: http://127.0.0.1:$vrProxyPort (separate window)"

            # Reuse an existing ngrok tunnel when still online (avoids ERR_NGROK_334 duplicate endpoint).
            $questVrHttpsUrl = Get-NgrokHttpsUrlForPort -Port $vrProxyPort
            if ($questVrHttpsUrl) {
                Write-Host "  Reusing existing ngrok HTTPS URL: $questVrHttpsUrl"
            }
            else {
                $ngrokProc = Start-QuestVrNgrokProcess -Port $vrProxyPort
                if ($ngrokProc) {
                    Write-Host '  ngrok started (separate window). Waiting for public HTTPS URL...'
                    $questVrHttpsUrl = Get-NgrokHttpsUrl -MaxSeconds 45 -Port $vrProxyPort
                }
                else {
                    Write-Warning 'Quest VR proxy is running, but ngrok was not started. WebXR on Quest still requires HTTPS.'
                }
            }

            if ($questVrHttpsUrl) {
                if (-not ($questVrHttpsUrl -match '^https://')) {
                    Write-Warning "Unexpected ngrok URL (expected https): $questVrHttpsUrl"
                }
                else {
                    Write-Host "  ngrok HTTPS URL: $questVrHttpsUrl"
                    $env:VITE_API_BASE = $questVrHttpsUrl
                    $env:VITE_GRAPHXR_VIEWER_URL = "$questVrHttpsUrl/viewer"
                    Write-Host '  Vite session env updated for Quest (overrides .env for this run).'
                }
            }
            elseif (-not $questVrHttpsUrl) {
                # ngrok window may show ERR_NGROK_334 while an old tunnel is still registered — try once more.
                $questVrHttpsUrl = Get-NgrokHttpsUrlForPort -Port $vrProxyPort
                if ($questVrHttpsUrl) {
                    Write-Host "  Recovered ngrok HTTPS URL from local agent: $questVrHttpsUrl"
                    $env:VITE_API_BASE = $questVrHttpsUrl
                    $env:VITE_GRAPHXR_VIEWER_URL = "$questVrHttpsUrl/viewer"
                }
                else {
                    Write-Warning 'Could not read ngrok HTTPS URL from http://127.0.0.1:4040/api/tunnels. Check the ngrok window.'
                    Write-Warning 'If ngrok reports ERR_NGROK_334, close the old ngrok window or run: Get-Process ngrok | Stop-Process -Force'
                }
            }
        }
        catch {
            Write-Warning ("Quest VR setup failed: $_")
            Write-Warning 'Continuing with normal local dev URLs only.'
        }
    }

    Write-Host '[4] Starting Vite on 0.0.0.0:5173 - laptop: http://127.0.0.1:5173'
    if ($QuestVR) {
        Write-QuestVrInstructions -QuestHttpsUrl $questVrHttpsUrl -LanIp $lanIp -ProxyPort $vrProxyPort
    }
    else {
        if ($lanIp) {
            Write-Host ("    Same WiFi iPad or phone: http://${lanIp}:5173")
            Write-Host ("    Atlas voice remote: http://${lanIp}:5173/atlas-remote")
        }
        else {
            Write-Host '    Same WiFi iPad or phone: http://YOUR_LAN_IP:5173 - run ipconfig to find IPv4'
            Write-Host '    Atlas voice remote: http://YOUR_LAN_IP:5173/atlas-remote'
        }
        Write-Host '    GraphXR viewer:' $env:VITE_GRAPHXR_VIEWER_URL
        Write-Host '    Optional .env: VITE_API_BASE=http://YOUR_LAN_IP:8787 if you bypass the Vite proxy.'
        Write-Host '    Meta Quest WebXR: run with -QuestVR for HTTPS proxy + ngrok.'
    }
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
    if ($QuestVR) {
        if ($ngrokProc -and -not $ngrokProc.HasExited) {
            Stop-Process -Id $ngrokProc.Id -Force -ErrorAction SilentlyContinue
        }
        if ($vrProxyProc -and -not $vrProxyProc.HasExited) {
            Stop-Process -Id $vrProxyProc.Id -Force -ErrorAction SilentlyContinue
        }
        Stop-StaleVrProxyProcesses -Port $vrProxyPort
    }
    if ($graphxrProc -and -not $graphxrProc.HasExited) {
        Stop-Process -Id $graphxrProc.Id -Force -ErrorAction SilentlyContinue
    }
    if (-not $SkipGraphXR) {
        Stop-StaleGraphXRProcesses -Port $graphxrPort
    }
    if ($bff -and -not $bff.HasExited) {
        Stop-Process -Id $bff.Id -Force -ErrorAction SilentlyContinue
    }
    if ($atlasApiProc -and -not $atlasApiProc.HasExited) {
        Stop-Process -Id $atlasApiProc.Id -Force -ErrorAction SilentlyContinue
    }
}
