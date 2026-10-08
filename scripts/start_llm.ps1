$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\environment.ps1"
try { $Host.UI.RawUI.WindowTitle = 'WAIFU LLM Server (llama-server, modo externo)' } catch { }

$port = 8290
$portText = "$env:WAIFU_LLM_PORT".Trim()
if ($portText) { $port = [int]$portText }

$ctx = 8192
$ctxText = "$env:WAIFU_LLM_CTX".Trim()
if ($ctxText) { $ctx = [int]$ctxText }

$threads = [math]::Max(4, [math]::Min(8, [int]([Environment]::ProcessorCount / 2)))
$threadsText = "$env:WAIFU_LLM_THREADS".Trim()
if ($threadsText) { $threads = [int]$threadsText }

$ngl = 0
$nglText = "$env:WAIFU_LLM_NGL".Trim()
if ($nglText) { $ngl = [int]$nglText }

$serverExe = Join-Path $StackRoot 'tools\llama.cpp\llama-server.exe'

$newModelDir = Join-Path $StackRoot 'ComfyUI\models\llm\qwen35-9b-nsfw-captioning'
$newModelPath = Join-Path $newModelDir 'qwen3.5-9b-nsfw-captioning-v5.Q4_K_M.gguf'
$newMmprojPath = Join-Path $newModelDir 'qwen3.5-9b-nsfw-captioning-v5.mmproj-Q8_0.gguf'

$legacyModelDir = Join-Path $StackRoot 'ComfyUI\models\llm\qwen35-9b-abliterated'
$legacyModelPath = Join-Path $legacyModelDir 'Qwen3.5-9B-abliterated-Q4_K_M.gguf'
$legacyMmprojPath = Join-Path $legacyModelDir 'mmproj-F16.gguf'

if ((Test-Path -LiteralPath $newModelPath) -and (Test-Path -LiteralPath $newMmprojPath)) {
    $modelPath = $newModelPath
    $mmprojPath = $newMmprojPath
} elseif ((Test-Path -LiteralPath $legacyModelPath) -and (Test-Path -LiteralPath $legacyMmprojPath)) {
    $modelPath = $legacyModelPath
    $mmprojPath = $legacyMmprojPath
} else {
    $modelPath = $newModelPath
    $mmprojPath = $newMmprojPath
}

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
$llamaArgs += "--host 127.0.0.1 --port $port -ngl $ngl -c $ctx -t $threads --jinja --reasoning off --no-webui -np 1".Split(' ')

$extraText = "$env:WAIFU_LLM_EXTRA_ARGS".Trim()
if ($extraText) {
    $llamaArgs += ($extraText -split ' ' | Where-Object { $_ })
}

Write-Host "Servidor LLM en http://127.0.0.1:$port (Ctrl+C para pararlo)"
Write-Host 'Modo externo opcional: la app ya arranca su propio servidor; usa este launcher solo si quieres servirlo aparte.'
Set-Location $StackRoot
& $serverExe @llamaArgs
exit $LASTEXITCODE
