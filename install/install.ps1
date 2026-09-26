<#
.SYNOPSIS
    Instalador idempotente de WAIFU en una maquina limpia (F3b / M10-6b).

.DESCRIPTION
    Preflight (Windows 10/11 x64 + GPU NVIDIA + >=140 GB libres) -> uv +
    CPython 3.12.12 -> .venv + requirements*.txt -> ComfyUI v0.34.0 pineado +
    dependencias del engine -> custom nodes pineados + ckpts RIFE +
    wheel SageAttention -> descarga y verificacion sha256 de los modelos de
    install\manifest\manifest.models.json (Civitai via $env:WAIFU_CIVITAI_TOKEN)
    -> variables WAIFU_COMFY_ROOT / WAIFU_COMFY_URL -> verificacion final
    (suite de tests + app.health).

    No contiene secretos: el token de Civitai solo se lee del entorno. Volver a
    ejecutarlo es seguro: omite lo ya hecho, verifica lo existente y solo
    descarga lo que falta. No descarga entradas obsolete ni las LoRAs de
    usuario (no redistribuibles); ver install\README_INSTALL.md.

.PARAMETER Root
    Raiz del repo WAIFU (por defecto el directorio padre de install\).
.PARAMETER SkipEngine
    No instala ComfyUI, custom nodes, torch, triton ni SageAttention.
.PARAMETER SkipModels
    No descarga modelos (si ya existen, los verifica).
.PARAMETER IncludeOptional
    Descarga tambien entradas required=false no obsoletas (R2V, stock del Editor).
.PARAMETER SkipVerify
    No ejecuta la suite de tests ni app.health al final.
.PARAMETER NoUserEnv
    No escribe WAIFU_COMFY_ROOT/WAIFU_COMFY_URL como variables de usuario.
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$SkipEngine,
    [switch]$SkipModels,
    [switch]$IncludeOptional,
    [switch]$SkipVerify,
    [switch]$NoUserEnv
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = [System.IO.Path]::GetFullPath($Root)

$ManifestDir        = Join-Path $PSScriptRoot 'manifest'
$ModelsManifestPath = Join-Path $ManifestDir 'manifest.models.json'
$NodesManifestPath  = Join-Path $ManifestDir 'manifest.nodes.json'
$StateDir           = Join-Path $Root '.install-state'
$ComfyRoot          = Join-Path $Root 'ComfyUI'
$ComfyModelsRoot    = Join-Path $ComfyRoot 'models'
$VenvPython         = Join-Path $Root '.venv\Scripts\python.exe'
$MinFreeBytes       = [long]140000000000
$ComfyUrl           = 'http://127.0.0.1:8288'
$CivitaiApiBase     = 'https://civitai.com/api/download/models/'
$Cu130Index         = 'https://download.pytorch.org/whl/cu130'
$script:Pending     = New-Object System.Collections.Generic.List[string]

function Write-Step {
    param([string]$Message)
    Write-Host ("==> {0}" -f $Message) -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host ("    OK  {0}" -f $Message) -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host ("    AVISO  {0}" -f $Message) -ForegroundColor Yellow
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw ("manifest no encontrado: {0}" -f $Path) }
    return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Invoke-Tool {
    param([string]$Label, [string]$Command, [string[]]$ToolArgs)
    Write-Host ("    > {0} {1}" -f $Command, ($ToolArgs -join ' '))
    & $Command @ToolArgs
    if ($LASTEXITCODE -ne 0) { throw ("{0}: fallo (exit {1})" -f $Label, $LASTEXITCODE) }
}

function Assert-FileHash {
    param([string]$Path, [string]$Sha256, [long]$Bytes)
    $item = Get-Item -LiteralPath $Path
    if ($Bytes -gt 0 -and $item.Length -ne $Bytes) {
        throw ("tamano incorrecto en {0}: {1} != {2}" -f $Path, $item.Length, $Bytes)
    }
    if ($Sha256) {
        $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $Sha256.ToLowerInvariant()) { throw ("sha256 incorrecto en {0}" -f $Path) }
    }
}

function Get-VerifiedFile {
    param([string]$Url, [string]$Destination, [string]$Sha256, [long]$Bytes)
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if (-not $curl) { throw 'curl.exe no disponible (lo incluye Windows 10 1803+).' }
    $tmp = $Destination + '.part'
    Write-Host ("    > curl -L --fail --retry 3 -C - -o {0}" -f $tmp)
    & curl.exe -L --fail --retry 3 --retry-delay 2 -C - -o $tmp $Url
    if ($LASTEXITCODE -ne 0) { throw ("descarga fallida (exit {0}): {1}" -f $LASTEXITCODE, $Url) }
    Assert-FileHash -Path $tmp -Sha256 $Sha256 -Bytes $Bytes
    Move-Item -LiteralPath $tmp -Destination $Destination -Force
}

function Invoke-Preflight {
    Write-Step 'preflight: SO, GPU NVIDIA y espacio libre'
    if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
        throw 'SO no soportado: se requiere Windows 10/11 x64.'
    }
    if (-not [System.Environment]::Is64BitOperatingSystem) { throw 'Se requiere Windows x64.' }
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    Write-Ok ("SO: {0}" -f $os.Caption.Trim())
    $gpus = @(Get-CimInstance -ClassName Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' })
    if ($gpus.Count -eq 0) { throw 'No se detecto GPU NVIDIA (requerida para torch cu130).' }
    Write-Ok ("GPU: {0}" -f $gpus[0].Name)
    $driveRoot = [System.IO.Path]::GetPathRoot($Root)
    $free = (New-Object System.IO.DriveInfo($driveRoot)).AvailableFreeSpace
    $freeGb = [math]::Round($free / 1e9, 1)
    if ($free -lt $MinFreeBytes) {
        throw ("Espacio libre insuficiente: {0} GB (minimo 140 GB)." -f $freeGb)
    }
    Write-Ok ("Espacio libre: {0} GB" -f $freeGb)
    if ($free -lt 140000000000) {
        Write-Warn 'espacio justo: el manifiesto required + engine ronda 139 GB; conviene liberar mas antes de continuar.'
    }
    foreach ($file in @($ModelsManifestPath, $NodesManifestPath)) {
        if (-not (Test-Path -LiteralPath $file)) { throw ("manifest no encontrado: {0}" -f $file) }
    }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
}

function Install-Uv {
    Write-Step 'uv'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        Write-Warn 'uv no esta en PATH; instalando con el instalador oficial de astral.sh'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-Expression (Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1')
        $env:Path = ("{0};{1}" -f (Join-Path $env:USERPROFILE '.local\bin'), $env:Path)
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if (-not $uv) { throw 'uv no quedo disponible tras la instalacion.' }
    }
    $version = (& uv --version) 2>&1
    Write-Ok ("uv: {0}" -f $version)
    if ($version -notmatch '0\.11\.14') {
        Write-Warn 'la version de uv difiere del pin auditado 0.11.14; se continua.'
    }
}

function Install-Python {
    Write-Step 'CPython 3.12.12 (uv-managed)'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Root 'python'
    Invoke-Tool -Label 'uv python install' -Command 'uv' -ToolArgs @(
        'python', 'install', '3.12.12', '--no-bin', '--no-registry'
    )
}

function Install-Venv {
    Write-Step '.venv + requirements de la app'
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Invoke-Tool -Label 'uv venv' -Command 'uv' -ToolArgs @(
            'venv', '--python', '3.12.12', (Join-Path $Root '.venv')
        )
    } else {
        Write-Ok ".venv ya existe"
    }
    $requirements = @(
        (Join-Path $Root 'requirements.txt'),
        (Join-Path $Root 'requirements-dev.txt')
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $pipArgs = @('pip', 'install', '--python', $VenvPython)
    foreach ($requirement in $requirements) { $pipArgs += @('-r', $requirement) }
    Invoke-Tool -Label 'uv pip install app' -Command 'uv' -ToolArgs $pipArgs
}

function Install-Engine {
    if ($SkipEngine) { Write-Warn 'SkipEngine: se omite ComfyUI, nodos, torch y SageAttention'; return }
    $nodes = Read-JsonFile $NodesManifestPath

    Write-Step ("ComfyUI {0} @ {1}" -f $nodes.comfyui.version, $nodes.comfyui.commit)
    if (-not (Test-Path -LiteralPath (Join-Path $ComfyRoot '.git'))) {
        Invoke-Tool -Label 'git clone ComfyUI' -Command 'git' -ToolArgs @(
            'clone', '--branch', $nodes.comfyui.tag, '--depth', '1', $nodes.comfyui.url, $ComfyRoot
        )
    }
    Invoke-Tool -Label 'git fetch ComfyUI' -Command 'git' -ToolArgs @(
        '-C', $ComfyRoot, 'fetch', '--all', '--tags', '--force'
    )
    Invoke-Tool -Label 'git checkout ComfyUI' -Command 'git' -ToolArgs @(
        '-C', $ComfyRoot, 'checkout', '--force', $nodes.comfyui.commit
    )
    $head = (& git -C $ComfyRoot rev-parse HEAD).Trim()
    if ($head -ne $nodes.comfyui.commit) {
        throw ("ComfyUI HEAD {0} != {1}" -f $head, $nodes.comfyui.commit)
    }
    Write-Ok ("ComfyUI @ {0}" -f $head)

    Invoke-Tool -Label 'engine requirements' -Command 'uv' -ToolArgs @(
        'pip', 'install', '--python', $VenvPython,
        '-r', (Join-Path $ComfyRoot 'requirements.txt')
    )
    Invoke-Tool -Label 'torch cu130' -Command 'uv' -ToolArgs @(
        'pip', 'install', '--python', $VenvPython,
        ("torch=={0}" -f $nodes.runtime.torch.torch),
        ("torchvision=={0}" -f $nodes.runtime.torch.torchvision),
        ("torchaudio=={0}" -f $nodes.runtime.torch.torchaudio),
        '--index-url', $Cu130Index
    )
    Invoke-Tool -Label 'triton_windows' -Command 'uv' -ToolArgs @(
        'pip', 'install', '--python', $VenvPython,
        ("triton_windows=={0}" -f $nodes.runtime.triton_windows)
    )
    Install-SageAttention -Nodes $nodes
    Install-CustomNodes -Nodes $nodes
}

function Install-SageAttention {
    param($Nodes)
    $sage = $Nodes.sageattention
    $cacheDir = Join-Path $Root 'cache\sage'
    $wheel = $null
    $local = Join-Path $Root ('data\downloads\sage\' + $sage.filename)
    $cached = Join-Path $cacheDir $sage.filename
    if (Test-Path -LiteralPath $local) { $wheel = $local }
    elseif (Test-Path -LiteralPath $cached) { $wheel = $cached }
    if (-not $wheel) {
        New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null
        $wheel = $cached
        Get-VerifiedFile -Url $sage.url -Destination $wheel -Sha256 $sage.sha256 -Bytes $sage.bytes
    }
    Assert-FileHash -Path $wheel -Sha256 $sage.sha256 -Bytes $sage.bytes
    Invoke-Tool -Label 'sageattention' -Command 'uv' -ToolArgs @(
        'pip', 'install', '--python', $VenvPython, '--no-deps', $wheel
    )
}

function Install-CustomNodes {
    param($Nodes)
    $nodesDir = Join-Path $ComfyRoot 'custom_nodes'
    New-Item -ItemType Directory -Force -Path $nodesDir | Out-Null
    foreach ($node in $Nodes.custom_nodes) {
        if ($node.obsolete -eq $true) {
            Write-Warn ("nodo obsoleto (no se instala): {0}" -f $node.id)
            continue
        }
        if ($node.required -eq $false -and -not $IncludeOptional) {
            Write-Warn ("nodo opcional omitido: {0}" -f $node.id)
            continue
        }
        $dir = Join-Path $nodesDir $node.id
        Write-Step ("nodo {0} @ {1}" -f $node.id, $node.commit)
        if (-not (Test-Path -LiteralPath (Join-Path $dir '.git'))) {
            if (Test-Path -LiteralPath $dir) {
                throw ("{0} existe y no es un repo git; muevelo o borralo y re-ejecuta." -f $dir)
            }
            Invoke-Tool -Label ("git clone {0}" -f $node.id) -Command 'git' -ToolArgs @(
                'clone', $node.url, $dir
            )
        }
        Invoke-Tool -Label ("git fetch {0}" -f $node.id) -Command 'git' -ToolArgs @(
            '-C', $dir, 'fetch', '--all', '--tags', '--force'
        )
        Invoke-Tool -Label ("git checkout {0}" -f $node.id) -Command 'git' -ToolArgs @(
            '-C', $dir, 'checkout', '--force', $node.commit
        )
        $head = (& git -C $dir rev-parse HEAD).Trim()
        if ($head -ne $node.commit) { throw ("{0} HEAD {1} != {2}" -f $node.id, $head, $node.commit) }
        $requirements = Join-Path $dir 'requirements.txt'
        if (Test-Path -LiteralPath $requirements) {
            Invoke-Tool -Label ("requirements {0}" -f $node.id) -Command 'uv' -ToolArgs @(
                'pip', 'install', '--python', $VenvPython, '-r', $requirements
            )
        }
        Write-Ok ("{0} @ {1}" -f $node.id, $head)
    }
}

function Install-Models {
    Write-Step 'modelos (install\manifest\manifest.models.json)'
    $manifest = Read-JsonFile $ModelsManifestPath
    $token = $env:WAIFU_CIVITAI_TOKEN
    $done = 0
    $skipped = 0
    foreach ($entry in $manifest.models) {
        if ($entry.obsolete -eq $true) { continue }
        if ($entry.required -eq $false -and -not $IncludeOptional) { $skipped++; continue }
        if ($SkipEngine -and $entry.subdir -like 'custom_nodes/*') {
            Write-Warn ("SkipEngine: se omite {0}" -f $entry.id)
            continue
        }
        $base = $ComfyModelsRoot
        if ($entry.root) { $base = Join-Path $Root $entry.root }
        $dir = Join-Path $base $entry.subdir
        $dest = Join-Path $dir $entry.filename
        $marker = Join-Path $StateDir (($entry.id -replace '[^A-Za-z0-9._-]', '_') + '.ok')
        if ((Test-Path -LiteralPath $dest) -and (Test-Path -LiteralPath $marker) -and
            ((Get-Item -LiteralPath $dest).Length -eq $entry.bytes)) {
            $done++
            continue
        }
        if (Test-Path -LiteralPath $dest) {
            Write-Host ("    verificando existente: {0}" -f $entry.id)
            Assert-FileHash -Path $dest -Sha256 $entry.sha256 -Bytes $entry.bytes
            New-Item -ItemType File -Force -Path $marker | Out-Null
            Write-Ok ("verificado: {0}" -f $entry.id)
            $done++
            continue
        }
        if ($SkipModels) {
            $script:Pending.Add($entry.id) | Out-Null
            continue
        }
        $url = $entry.url
        if ($url -eq 'URL_VERIFICAR') {
            if ($entry.civitai_version_id -and $token) {
                $url = "{0}{1}?token={2}" -f $CivitaiApiBase, $entry.civitai_version_id, $token
            } else {
                Write-Warn ("sin URL publica verificada; aportar manualmente: {0}" -f $entry.id)
                $script:Pending.Add($entry.id) | Out-Null
                continue
            }
        }
        if (-not $url) {
            Write-Warn ("sin URL (archivo del usuario, no redistribuible): {0}" -f $entry.id)
            $script:Pending.Add($entry.id) | Out-Null
            continue
        }
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        Write-Step ("descarga {0} ({1} GB)" -f $entry.id, [math]::Round($entry.bytes / 1e9, 2))
        Get-VerifiedFile -Url $url -Destination $dest -Sha256 $entry.sha256 -Bytes $entry.bytes
        New-Item -ItemType File -Force -Path $marker | Out-Null
        Write-Ok ("verificado: {0}" -f $entry.id)
        $done++
    }
    Write-Ok ("modelos listos: {0} (opcionales omitidos: {1})" -f $done, $skipped)
    if ($script:Pending.Count -gt 0) {
        Write-Warn ("pendientes de aporte manual: {0}" -f ($script:Pending -join ', '))
        Write-Warn 'Civitai: define $env:WAIFU_CIVITAI_TOKEN y re-ejecuta; el resto, copia el archivo con nombre/subdir exactos del manifiesto.'
    }
}

function Write-Environment {
    Write-Step 'variables de entorno (WAIFU_COMFY_ROOT / WAIFU_COMFY_URL)'
    $envFile = Join-Path $PSScriptRoot 'env.ps1'
    $quotedRoot = $ComfyRoot.Replace("'", "''")
    Set-Content -LiteralPath $envFile -Encoding UTF8 -Value @(
        '# Generado por install.ps1 (M10-6b); no contiene secretos.',
        ("`$env:WAIFU_COMFY_ROOT = '{0}'" -f $quotedRoot),
        ("`$env:WAIFU_COMFY_URL = '{0}'" -f $ComfyUrl)
    )
    if (-not $NoUserEnv) {
        [Environment]::SetEnvironmentVariable('WAIFU_COMFY_ROOT', $ComfyRoot, 'User')
        [Environment]::SetEnvironmentVariable('WAIFU_COMFY_URL', $ComfyUrl, 'User')
        Write-Ok 'variables de usuario escritas (aplican a procesos nuevos)'
    }
    $env:WAIFU_COMFY_ROOT = $ComfyRoot
    $env:WAIFU_COMFY_URL = $ComfyUrl
    Write-Ok ("WAIFU_COMFY_ROOT={0} ; WAIFU_COMFY_URL={1}" -f $ComfyRoot, $ComfyUrl)
}

function Invoke-FinalVerification {
    Write-Step 'verificacion final'
    if ($SkipVerify) { Write-Warn 'SkipVerify: sin suite ni app.health'; return }
    if (-not (Test-Path -LiteralPath $VenvPython)) { throw '.venv ausente: no se puede verificar.' }
    Push-Location $Root
    try {
        & $VenvPython -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) { throw ("suite de tests en rojo (exit {0})" -f $LASTEXITCODE) }
        Write-Ok 'suite verde'
        & $VenvPython -m app.health
        if ($LASTEXITCODE -ne 0) { throw 'app.health fallo (rutas criticas)' }
        & $VenvPython -m app.health --require-engine 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Ok 'engine responde: app.health --require-engine OK'
        } else {
            Write-Warn 'engine no responde todavia; arranca scripts\start_engine.ps1 y repite: .venv\Scripts\python.exe -m app.health --require-engine'
        }
    } finally {
        Pop-Location
    }
}

Write-Host ''
Write-Host 'WAIFU installer (F3b / M10-6b)' -ForegroundColor Cyan
Write-Host ("Raiz: {0}" -f $Root)

Invoke-Preflight
$environmentScript = Join-Path $Root 'scripts\environment.ps1'
if (Test-Path -LiteralPath $environmentScript) { . $environmentScript }

Install-Uv
Install-Python
Install-Venv
Install-Engine
Install-Models
Write-Environment
Invoke-FinalVerification

Write-Host ''
if ($script:Pending.Count -gt 0) {
    Write-Warn ("Entradas pendientes de aporte manual: {0}" -f ($script:Pending -join ', '))
    Write-Warn 'Si alguna es required, el producto no queda completo: aporta el archivo o el token y re-ejecuta.'
}
Write-Host 'Instalacion terminada. Siguientes pasos:' -ForegroundColor Green
Write-Host '  1) .\scripts\start_engine.ps1'
Write-Host '  2) .\.venv\Scripts\python.exe -m app.health --require-engine'
Write-Host '  3) .\scripts\start_app.ps1  (o INICIAR_WAIFU.bat)'
if ($script:Pending.Count -gt 0) { exit 2 }
exit 0
