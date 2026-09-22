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
& (Join-Path $StackRoot '.venv\Scripts\python.exe') -s main.py --listen 127.0.0.1 --port 8288 --disable-api-nodes --disable-auto-launch
exit $LASTEXITCODE
