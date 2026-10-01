$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"
try { $Host.UI.RawUI.WindowTitle = 'WAIFU LLM Server (llama-server)' } catch { }

$port = 8290
$portText = "$env:WAIFU_LLM_PORT".Trim()
if ($portText) { $port = [int]$portText }

$ctx = 8192
$ctxText = "$env:WAIFU_LLM_CTX".Trim()
if ($ctxText) { $ctx = [int]$ctxText }

$draftMax = 2
$draftText = "$env:WAIFU_LLM_DRAFT_NMAX".Trim()
if ($draftText) { $draftMax = [int]$draftText }

$serverExe = Join-Path $StackRoot 'tools\llama.cpp\llama-server.exe'
$modelDir = Join-Path $StackRoot 'ComfyUI\models\llm\qwen38-27b-uncensored'
$modelPath = Join-Path $modelDir 'qwen3.8-27b-abliterated-3.69bpw-12GB-MTP.gguf'
$mmprojPath = Join-Path $modelDir 'mmproj-Qwen3.8-27B-AEON-ULTIMATE-UNCENSORED-BF16.gguf'

$missing = @()
if (!(Test-Path -LiteralPath $serverExe)) { $missing += "llama-server.exe: $serverExe" }
if (!(Test-Path -LiteralPath $modelPath)) { $missing += "modelo: $modelPath" }
if (!(Test-Path -LiteralPath $mmprojPath)) { $missing += "mmproj: $mmprojPath" }
if ($missing.Count -gt 0) {
    Write-Host 'No se puede arrancar el servidor LLM. Faltan archivos:'
    foreach ($item in $missing) { Write-Host "  - $item" }
    Write-Host 'Descargalos con: & .\.venv\Scripts\python.exe scripts\download_llm.py'
    exit 1
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    $llamaRoot = Join-Path $StackRoot 'tools\llama.cpp'
    if ($owner.ExecutablePath -like "$llamaRoot\*") {
        Write-Host "El servidor LLM ya esta corriendo: http://127.0.0.1:$port"
        exit 0
    }
    Write-Host "Puerto $port ocupado por otra aplicacion ($($owner.ExecutablePath)). No se arranco nada."
    exit 1
}

$llamaArgs = @(
    '-m', $modelPath,
    '--mmproj', $mmprojPath
)

if (Test-Path Env:WAIFU_LLM_DEVICE) {
    $deviceText = "$env:WAIFU_LLM_DEVICE".Trim()
    if ($deviceText -and $deviceText -ne 'all') {
        $llamaArgs += @('--device', $deviceText)
        $deviceLabel = $deviceText
    } else {
        $deviceLabel = 'todas (WAIFU_LLM_DEVICE vacio/all)'
    }
} else {
    $llamaArgs += @('--device', 'CUDA0')
    $deviceLabel = 'CUDA0 (solo la 3060)'
}

$llamaArgs += "--host 127.0.0.1 --port $port --jinja -fa on -c $ctx -ctk q4_0 -ctv q4_0".Split(' ')
$llamaArgs += "--spec-type draft-mtp --spec-draft-n-max $draftMax -np 1 --reasoning off".Split(' ')

$nglText = "$env:WAIFU_LLM_NGL".Trim()
if ($nglText) {
    $llamaArgs += "-ngl $nglText --fit off".Split(' ')
} else {
    $llamaArgs += '--fit on'.Split(' ')
}

if ("$env:WAIFU_LLM_MMPROJ_GPU".Trim() -ne '1') {
    $llamaArgs += '--no-mmproj-offload'
}

$extraText = "$env:WAIFU_LLM_EXTRA_ARGS".Trim()
if ($extraText) {
    $llamaArgs += ($extraText -split ' ' | Where-Object { $_ })
}

Write-Host "Servidor LLM en http://127.0.0.1:$port (Ctrl+C para pararlo)"
Write-Host "GPU del LLM: $deviceLabel. WAIFU_LLM_DEVICE la cambia (por defecto CUDA0 = 3060)."
Set-Location $StackRoot
& $serverExe @llamaArgs
exit $LASTEXITCODE
