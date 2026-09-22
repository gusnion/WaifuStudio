param([int]$Port = 8288)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$listener) { Write-Host 'El engine ya esta parado.'; exit 0 }

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$expected = Join-Path $root '.venv\Scripts\python.exe'
$managedPython = Join-Path $root 'python\cpython-3.12.12-windows-x86_64-none\python.exe'
$parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ParentProcessId)"
$owned = ($process.ExecutablePath -eq $expected) -or ($process.ExecutablePath -eq $managedPython -and $parent.ExecutablePath -eq $expected)
if (!$owned -or $process.CommandLine -notmatch ' main\.py ') {
    throw "El puerto $Port pertenece a otra aplicacion. No se detuvo nada."
}

$queue = Invoke-RestMethod "http://127.0.0.1:$Port/queue" -TimeoutSec 5
if ($queue.queue_running.Count -gt 0 -or $queue.queue_pending.Count -gt 0) {
    throw 'Hay jobs activos o pendientes. Termina o cancelalos en ComfyUI primero.'
}

Stop-Process -Id $listener.OwningProcess
Write-Host 'Engine detenido.'
