$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"

$listener = Get-NetTCPConnection -LocalPort 8288 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $expected = Join-Path $StackRoot '.venv\Scripts\python.exe'
    $managedPython = Join-Path $StackRoot 'python\cpython-3.12.12-windows-x86_64-none\python.exe'
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.ParentProcessId)"
    $owned = ($owner.ExecutablePath -eq $expected) -or ($owner.ExecutablePath -eq $managedPython -and $parent.ExecutablePath -eq $expected)
    if (!$owned -or $owner.CommandLine -notmatch ' main\.py ') {
        throw 'Puerto 8288 ocupado por otra aplicacion.'
    }
    Write-Host 'El engine de WAIFU ya esta corriendo: http://127.0.0.1:8288'
    exit 0
}

Set-Location (Join-Path $StackRoot 'ComfyUI')
# El equipo puede exponer una iGPU/2060 como GPU 0. ComfyUI solo debe ver la
# GPU de mayor VRAM para no partir el modelo ni bloquear la maquina.
$gpuLines = & nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader,nounits 2>$null
$bestGpu = $gpuLines | ForEach-Object {
    $parts = $_ -split ','
    if ($parts.Count -ge 3) {
        [pscustomobject]@{
            Index = [int]$parts[0].Trim()
            Name  = $parts[1].Trim()
            Mib   = [int]$parts[2].Trim()
        }
    }
} | Sort-Object Mib -Descending | Select-Object -First 1
if ($bestGpu) {
    $env:CUDA_VISIBLE_DEVICES = [string]$bestGpu.Index
    Write-Host ("Engine GPU: {0} ({1} MiB, indice {2})" -f $bestGpu.Name, $bestGpu.Mib, $bestGpu.Index)
}
& (Join-Path $StackRoot '.venv\Scripts\python.exe') -s main.py --listen 127.0.0.1 --port 8288 --offline --disable-auto-launch
exit $LASTEXITCODE
