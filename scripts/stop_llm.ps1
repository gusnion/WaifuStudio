param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if ($Port -eq 0) {
    $portText = "$env:WAIFU_LLM_PORT".Trim()
    $Port = if ($portText) { [int]$portText } else { 8290 }
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$listener) { Write-Host 'El servidor LLM ya esta parado.'; exit 0 }

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
$llamaRoot = Join-Path $root 'tools\llama.cpp'
if ($process.ExecutablePath -notlike "$llamaRoot\*") {
    Write-Host "El puerto $Port pertenece a otra aplicacion ($($process.ExecutablePath)). No se detuvo nada."
    exit 1
}

Stop-Process -Id $listener.OwningProcess
Write-Host 'Servidor LLM detenido.'
exit 0
