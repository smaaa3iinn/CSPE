# Stop all product-shell uvicorn listeners on port 8787 (fixes stale / duplicate binds on Windows).
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

Write-Host 'Stopping product API processes (port 8787)...'

function Stop-ProcessTree {
    param([int]$ProcId)
    if ($ProcId -le 0) { return }
    taskkill /F /T /PID $ProcId 2>$null | Out-Null
}

function Test-ProductShellCommandLine {
    param([string]$Cmd)
    if (-not $Cmd) { return $false }
    $isUvicorn = ($Cmd -like '*uvicorn*') -and ($Cmd -like '*product_shell*')
    $isPort8787 = ($Cmd -like '*8787*') -and ($Cmd -like '*product_shell*')
    return ($isUvicorn -or $isPort8787)
}

# 1) Match by command line (venv, store Python, py launcher).
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { Test-ProductShellCommandLine -Cmd $_.CommandLine } |
    ForEach-Object {
        Write-Host "  taskkill /T /PID $($_.ProcessId)"
        Write-Host "    $($_.CommandLine)"
        Stop-ProcessTree -ProcId $_.ProcessId
    }

# 2) PIDs from netstat LISTENING on 8787.
$pids = @()
netstat -ano -p tcp | Select-String ':8787' | Select-String 'LISTENING' | ForEach-Object {
    $parts = ($_.Line -replace '\s+', ' ').Trim().Split(' ')
    $procId = [int]$parts[-1]
    if ($procId -gt 0) { $pids += $procId }
}
foreach ($procId in ($pids | Select-Object -Unique)) {
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "  taskkill /T /PID $procId ($($proc.ProcessName))"
        Stop-ProcessTree -ProcId $procId
    }
}

Start-Sleep -Seconds 2

$listeners = @(netstat -ano -p tcp | Select-String ':8787' | Select-String 'LISTENING')
if ($listeners.Count -eq 0) {
    Write-Host 'Port 8787: no LISTENING entries.'
} else {
    Write-Host "Port 8787: still shows $($listeners.Count) LISTENING line(s) in netstat:"
    $listeners | ForEach-Object { Write-Host "  $($_.Line.Trim())" }
    Write-Host ''
    Write-Host 'If http://127.0.0.1:8787/api/health still responds, reboot once to clear orphaned sockets.'
}

try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 2 -ErrorAction Stop
    $explore = $false
    if ($h.capabilities -and $h.capabilities.PSObject.Properties['transport_exploration']) {
        $explore = [bool]$h.capabilities.transport_exploration
    }
    if ($explore) {
        Write-Host 'Health OK with transport_exploration=true (current build).'
    } else {
        Write-Warning 'Health still responds but transport_exploration is missing (OLD build). Reboot, then run .\run_web_app.ps1'
    }
} catch {
    Write-Host 'Health unreachable on :8787 (port is free for a fresh start).'
}
