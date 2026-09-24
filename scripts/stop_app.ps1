param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if ($Port -eq 0) {
    $portText = "$env:WAIFU_APP_PORT".Trim()
    $Port = if ($portText) { [int]$portText } else { 8765 }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$listener) { Write-Host 'La app ya esta detenida.'; exit 0 }

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$expected = Join-Path $root '.venv\Scripts\python.exe'
$managedPython = Join-Path $root 'python\cpython-3.12.12-windows-x86_64-none\python.exe'
$parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.ParentProcessId)"
$owned = ($process.ExecutablePath -eq $expected) -or ($process.ExecutablePath -eq $managedPython -and $parent.ExecutablePath -eq $expected)
if (!$owned -or $process.CommandLine -notmatch 'app\.server') {
    throw "El puerto $Port pertenece a otra aplicacion. No se detuvo nada."
}

Stop-Process -Id $listener.OwningProcess
Write-Host 'App detenida.'
exit 0
