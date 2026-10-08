$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"

$port = 8765
$portText = "$env:WAIFU_APP_PORT".Trim()
if ($portText) { $port = [int]$portText }

# 1. Comprobar si el Engine (ComfyUI) está corriendo; si no, arrancarlo
$engineListener = Get-NetTCPConnection -LocalPort 8288 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$engineListener) {
    Write-Host "Iniciando Engine ComfyUI (8288) en segundo plano..." -ForegroundColor Cyan
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\start_engine.ps1`"" -WindowStyle Minimized
}

# 2. Comprobar si el servidor WaifuStudio está corriendo; si no, arrancarlo
$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (!$listener) {
    Write-Host "Iniciando servidor WaifuStudio en segundo plano..." -ForegroundColor Cyan
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\start_app.ps1`"" -WindowStyle Minimized
    # Esperar hasta 10 segundos a que el puerto responda
    $ready = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) { $ready = $true; break }
    }
    if (!$ready) {
        Write-Warning "El servidor tardo en iniciar, abriendo la ventana de todas formas..."
    }
}

# 2. Localizar navegador ligero (Edge o Chrome)
$edgeCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LocalAppData\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)

$browserPath = $null
foreach ($cand in $edgeCandidates) {
    if (Test-Path $cand) {
        $browserPath = $cand
        break
    }
}

$url = "http://127.0.0.1:$port"
$profileDir = Join-Path $env:LOCALAPPDATA "WaifuStudio\browser_profile"

if ($browserPath) {
    $browserArgs = @(
        "--app=$url",
        "--window-size=1360,860",
        "--user-data-dir=`"$profileDir`"",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--no-first-run",
        "--no-default-browser-check"
    ) -join " "

    Start-Process -FilePath $browserPath -ArgumentList $browserArgs
    Write-Host "Ventana de WaifuStudio abierta en modo app ultraligera (~100 MB RAM)." -ForegroundColor Green
} else {
    Write-Host "Abriendo en navegador predeterminado..."
    Start-Process $url
}
