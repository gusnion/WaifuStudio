$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"

$port = 8765
$portText = "$env:WAIFU_APP_PORT".Trim()
if ($portText) { $port = [int]$portText }

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $expected = Join-Path $StackRoot '.venv\Scripts\python.exe'
    $managedPython = Join-Path $StackRoot 'python\cpython-3.12.12-windows-x86_64-none\python.exe'
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.ParentProcessId)"
    $owned = ($owner.ExecutablePath -eq $expected) -or ($owner.ExecutablePath -eq $managedPython -and $parent.ExecutablePath -eq $expected)
    if (!$owned -or $owner.CommandLine -notmatch 'app\.server') {
        throw "Puerto $port ocupado por otra aplicacion."
    }
    Write-Host "La app ya esta corriendo: http://127.0.0.1:$port"
    exit 0
}

Set-Location $StackRoot
& (Join-Path $StackRoot '.venv\Scripts\python.exe') -m app.server
exit $LASTEXITCODE
