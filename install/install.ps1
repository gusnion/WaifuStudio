<#
.SYNOPSIS
    Instalador idempotente de WAIFU en una maquina limpia (F3b / M10-6b).

.DESCRIPTION
    Preflight (Windows 10/11 x64 + GPU NVIDIA + >=140 GB libres) -> uv +
    CPython 3.12.12 -> .venv + requirements*.txt -> ComfyUI v0.42.5 pineado +
    dependencias del engine -> custom nodes pineados + ckpts RIFE +
    wheel SageAttention -> FFmpeg/FFprobe portables en tools\ffmpeg ->
    PREGUNTA "instalar modelos recomendados" con el
    espacio estimado (se omite la pregunta con -SkipModels o -Yes) -> descarga
    y verificacion sha256 de install\manifest\manifest.models.json (los assets
    sin URL publica verificada quedan como aporte manual) -> registra en la
    capa de usuario data\registry\models.json los modelos recomendados que ya
    esten en disco -> variables WAIFU_COMFY_ROOT / WAIFU_COMFY_URL -> verificacion
    final (suite de tests + app.health).

    No contiene secretos. Volver a
    ejecutarlo es seguro: omite lo ya hecho, verifica lo existente y solo
    descarga lo que falta. No descarga entradas obsolete ni las LoRAs de
    usuario (no redistribuibles); ver install\README_INSTALL.md.

.PARAMETER Root
    Raiz del repo WAIFU (por defecto el directorio padre de install\).
.PARAMETER SkipEngine
    No instala ComfyUI, custom nodes, torch, triton ni SageAttention.
.PARAMETER SkipModels
    No descarga modelos (si ya existen, los verifica) y omite la pregunta.
.PARAMETER Yes
    Modo desatendido: instala los modelos recomendados sin preguntar.
.PARAMETER IncludeOptional
    Descarga tambien entradas required=false no obsoletas (R2V, stock del Editor).
.PARAMETER SkipVerify
    No ejecuta la suite de tests ni app.health al final.
.PARAMETER FullTests
    Fuerza la suite completa aunque falten datos de usuario o el entrenador.
.PARAMETER SkipFfmpeg
    No descarga FFmpeg/FFprobe portables (Timeline, fade y concatenado no funcionaran).
.PARAMETER NoUserEnv
    No escribe WAIFU_COMFY_ROOT/WAIFU_COMFY_URL como variables de usuario.
.PARAMETER NoShortcut
    No crea/actualiza WAIFUSTUDIO.lnk con el icono de la app.
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$SkipEngine,
    [switch]$SkipModels,
    [switch]$SkipLlm,
    [switch]$Yes,
    [switch]$IncludeOptional,
    [switch]$IncludeTrainer,
    [switch]$SkipVerify,
    [switch]$FullTests,
    [switch]$SkipFfmpeg,
    [switch]$NoUserEnv,
    [switch]$NoShortcut
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
$MinFreeBytes       = [long]25000000000
$ComfyUrl           = 'http://127.0.0.1:8288'
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
        $hash = $null
        for ($try = 1; $try -le 5; $try++) {
            try {
                $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
                break
            } catch {
                if ($try -eq 5) { throw }
                Start-Sleep -Seconds 2
            }
        }
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
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if (-not $gitCmd) {
        throw 'git no encontrado en PATH. Instala Git for Windows y re-ejecuta.'
    }
    $gpus = @(Get-CimInstance -ClassName Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' })
    if ($gpus.Count -eq 0) { throw 'No se detecto GPU NVIDIA (requerida para torch cu130).' }
    Write-Ok ("GPU: {0}" -f $gpus[0].Name)
    $smiCmd = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if ($smiCmd) {
        try {
            $smiOut = (& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
            if ($smiOut) {
                $gpuLines = @($smiOut)
                $bestGpu = $gpuLines | ForEach-Object {
                    $parts = $_ -split ','
                    if ($parts.Count -ge 3) {
                        [pscustomobject]@{
                            Name   = $parts[0].Trim()
                            Mib    = [double]$parts[1].Trim()
                            Driver = $parts[2].Trim()
                        }
                    }
                } | Sort-Object Mib -Descending | Select-Object -First 1
                if ($bestGpu) {
                    $gpuName = $bestGpu.Name
                    $gpuMemMb = $bestGpu.Mib
                    $driverVer = $bestGpu.Driver
                    Write-Ok ("NVIDIA-SMI: {0} | VRAM: {1} MB | Driver: {2}" -f $gpuName, $gpuMemMb, $driverVer)
                    if ($gpuMemMb -lt 8000) {
                        Write-Warn ("VRAM detectada ({0} MB) inferior a 8000 MB; modelos grandes o video pueden requerir perfiles ligeros." -f $gpuMemMb)
                    }
                    $driverMajor = [int]($driverVer.Split('.')[0])
                    if ($driverMajor -lt 570) {
                        Write-Warn 'Driver NVIDIA anterior a 570.xx detectado; para torch cu130 se recomienda actualizar el driver NVIDIA a 570.xx o superior.'
                    }
                }
            }
        } catch {
            Write-Warn ("No se pudo consultar detalles completos con nvidia-smi: {0}" -f $_.Exception.Message)
        }
    }
    $driveRoot = [System.IO.Path]::GetPathRoot($Root)
    $free = (New-Object System.IO.DriveInfo($driveRoot)).AvailableFreeSpace
    $freeGb = [math]::Round($free / 1e9, 1)
    if ($free -lt $MinFreeBytes) {
        throw ("Espacio libre insuficiente: {0} GB (minimo 25 GB)." -f $freeGb)
    }
    Write-Ok ("Espacio libre: {0} GB" -f $freeGb)
    if ($free -lt 125000000000 -and -not $SkipModels) {
        Write-Warn 'Menos de 125 GB libres: el paquete completo de modelos requiere ~115 GB; puedes responder n en la pregunta de modelos o usar -SkipModels.'
    }
    foreach ($file in @($ModelsManifestPath, $NodesManifestPath)) {
        if (-not (Test-Path -LiteralPath $file)) { throw ("manifest no encontrado: {0}" -f $file) }
    }
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
}

function Install-Uv {
    Write-Step 'uv'
    $localUvDir = Join-Path $Root 'tools\uv'
    $localUvExe = Join-Path $localUvDir 'uv.exe'
    if (Test-Path -LiteralPath $localUvExe) {
        $env:Path = ("{0};{1}" -f $localUvDir, $env:Path)
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    $needInstall = $false
    if (-not $uv) {
        $needInstall = $true
    } else {
        $version = (& uv --version) 2>&1
        if ($version -match 'uv 0\.[0-7]\.') {
            $needInstall = $true
        }
    }
    if ($needInstall) {
        Write-Warn 'uv no esta en PATH o su version es antigua; instalando con el instalador oficial de astral.sh'
        $env:UV_INSTALL_DIR = $localUvDir
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-Expression (Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1')
        $env:Path = ("{0};{1};{2}" -f $localUvDir, (Join-Path $env:USERPROFILE '.local\bin'), $env:Path)
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
        'python', 'install', '3.12.12', '--python-preference', 'only-managed', '--no-bin', '--no-registry'
    )
}

function Install-Venv {
    Write-Step '.venv + requirements de la app'
    $managedPy = Join-Path $Root 'python\cpython-3.12.12-windows-x86_64-none\python.exe'
    $venvDir = Join-Path $Root '.venv'
    $cfgPath = Join-Path $venvDir 'pyvenv.cfg'
    $managedPyDir = Join-Path $Root 'python'
    if (Test-Path -LiteralPath $venvDir) {
        $needRecreate = $false
        if (-not (Test-Path -LiteralPath $cfgPath)) {
            $needRecreate = $true
        } else {
            $cfgContent = Get-Content -LiteralPath $cfgPath -Raw -ErrorAction SilentlyContinue
            if (-not $cfgContent -or -not ($cfgContent.Contains($managedPyDir))) {
                $needRecreate = $true
            }
        }
        if ($needRecreate) {
            Write-Warn '.venv existente apunta a un Python externo; recreando .venv hermetico...'
            Remove-Item -LiteralPath $venvDir -Recurse -Force
        }
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        if (Test-Path -LiteralPath $managedPy) {
            Invoke-Tool -Label 'uv venv' -Command 'uv' -ToolArgs @(
                'venv', '--python', $managedPy, '--python-preference', 'only-managed', $venvDir
            )
        } else {
            Invoke-Tool -Label 'uv venv' -Command 'uv' -ToolArgs @(
                'venv', '--python', '3.12.12', $venvDir
            )
        }
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
    Install-CustomNodes -Nodes $nodes
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
    try {
        Invoke-Tool -Label 'sageattention' -Command 'uv' -ToolArgs @(
            'pip', 'install', '--python', $VenvPython, '--no-deps', $wheel
        )
    } catch {
        Write-Warn ('SageAttention opcional no pudo instalarse ({0}); el engine usara atencion estandar.' -f $_.Exception.Message)
    }
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
                Write-Warn ("{0} existe y no es un repo git; eliminando para clonado limpio..." -f $dir)
                Remove-Item -LiteralPath $dir -Recurse -Force
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
        $requirementsNoCupy = Join-Path $dir 'requirements-no-cupy.txt'
        if (Test-Path -LiteralPath $requirements) {
            Invoke-Tool -Label ("requirements {0}" -f $node.id) -Command 'uv' -ToolArgs @(
                'pip', 'install', '--python', $VenvPython, '-r', $requirements
            )
        } elseif (Test-Path -LiteralPath $requirementsNoCupy) {
            Invoke-Tool -Label ("requirements-no-cupy {0}" -f $node.id) -Command 'uv' -ToolArgs @(
                'pip', 'install', '--python', $VenvPython, '-r', $requirementsNoCupy
            )
        }
        Write-Ok ("{0} @ {1}" -f $node.id, $head)
    }

    $localNodes = @('waifu_anima_patch')
    foreach ($localNode in $localNodes) {
        $sourceDir = Join-Path (Join-Path $Root 'tools\custom_nodes') $localNode
        $targetDir = Join-Path $nodesDir $localNode
        if (Test-Path -LiteralPath $sourceDir) {
            if (-not (Test-Path -LiteralPath $targetDir)) {
                Write-Step ("vinculando nodo local {0}" -f $localNode)
                try {
                    New-Item -ItemType Junction -Path $targetDir -Target $sourceDir -ErrorAction Stop | Out-Null
                    Write-Ok ("junction {0} -> {1}" -f $localNode, $targetDir)
                } catch {
                    Copy-Item -Recurse -Force -Path $sourceDir -Destination $targetDir
                    Write-Ok ("copia {0} -> {1}" -f $localNode, $targetDir)
                }
            } else {
                Write-Ok ("nodo local presente: {0}" -f $localNode)
            }
        }
    }
}

function Install-Trainer {
    $kohyaRoot = Join-Path $Root 'tools\kohya'
    $sdScriptsDir = Join-Path $kohyaRoot 'sd-scripts'
    $trainerVenv = Join-Path $kohyaRoot 'venv'
    $trainerPython = Join-Path $trainerVenv 'Scripts\python.exe'

    if (-not (Test-Path -LiteralPath $kohyaRoot)) {
        New-Item -ItemType Directory -Force -Path $kohyaRoot | Out-Null
    }
    Write-Step 'entrenador LoRA Anima (tools\kohya)'
    if (-not (Test-Path -LiteralPath (Join-Path $sdScriptsDir '.git'))) {
        Write-Step 'clonando kohya-ss/sd-scripts (tag v0.12.0)'
        Invoke-Tool -Label 'git clone sd-scripts' -Command 'git' -ToolArgs @(
            'clone', '--branch', 'v0.12.0', '--depth', '1',
            'https://github.com/kohya-ss/sd-scripts.git', $sdScriptsDir
        )
    } else {
        Write-Ok 'sd-scripts presente'
    }

    if (-not (Test-Path -LiteralPath $trainerPython)) {
        Write-Step 'creando venv para tools\kohya'
        Invoke-Tool -Label 'uv venv kohya' -Command 'uv' -ToolArgs @(
            'venv', '--python', '3.12.12', $trainerVenv
        )
        Invoke-Tool -Label 'uv pip torch kohya' -Command 'uv' -ToolArgs @(
            'pip', 'install', '--python', $trainerPython,
            'torch==2.11.0+cu130', 'torchvision==0.26.0+cu130',
            '--extra-index-url', 'https://download.pytorch.org/whl/cu130'
        )
        $reqFile = Join-Path $sdScriptsDir 'requirements.txt'
        if (Test-Path -LiteralPath $reqFile) {
            Invoke-Tool -Label 'uv pip requirements kohya' -Command 'uv' -ToolArgs @(
                'pip', 'install', '--python', $trainerPython, '-r', $reqFile
            )
        }
    } else {
        Write-Ok 'venv tools\kohya presente'
    }

    $wrapper = Join-Path $kohyaRoot 'run_waifu_train.py'
    if (Test-Path -LiteralPath $wrapper) {
        $trainerCmd = ("{0} {1}" -f $trainerPython, $wrapper)
        if (-not $NoUserEnv) {
            [Environment]::SetEnvironmentVariable('WAIFU_TRAINER_CMD', $trainerCmd, 'User')
            Write-Ok ("WAIFU_TRAINER_CMD configurado: {0}" -f $trainerCmd)
        }
    }
}


function Install-Models {
    Write-Step 'modelos (install\manifest\manifest.models.json)'
    $manifest = Read-JsonFile $ModelsManifestPath
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
            Write-Warn ("sin URL publica verificada; aporte manual (ver README_INSTALL): {0}" -f $entry.id)
            $script:Pending.Add($entry.id) | Out-Null
            continue
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
    if (-not $SkipModels) {
        $downloadModelsScript = Join-Path $Root 'scripts\download_models.py'
        if (Test-Path -LiteralPath $downloadModelsScript) {
            try {
                Invoke-Tool -Label 'download_vdn' -Command $VenvPython -ToolArgs @($downloadModelsScript, '--vdn')
            } catch {
                Write-Warn ("Descarga automatica de adaptadores VDN fallo ({0}); puedes reintentar con 'python scripts\download_models.py --vdn'." -f $_.Exception.Message)
            }
        }
    }
    if ($script:Pending.Count -gt 0) {
        Write-Warn ("pendientes de aporte manual: {0}" -f ($script:Pending -join ', '))
        Write-Warn 'Copia los archivos pendientes con nombre y subdir exactos del manifiesto (ver install\README_INSTALL.md).'
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
        $hasUserData = Test-Path -LiteralPath (Join-Path $Root 'data\registry\loras.json')
        $hasTrainer = Test-Path -LiteralPath (Join-Path $Root 'tools\kohya\sd-scripts\anima_train_network.py')
        if ($FullTests -or ($hasUserData -and $hasTrainer)) {
            & $VenvPython -m unittest discover -s tests
            if ($LASTEXITCODE -ne 0) { throw ("suite de tests en rojo (exit {0})" -f $LASTEXITCODE) }
            Write-Ok 'suite verde'
        } else {
            & $VenvPython -m unittest tests.test_first_run tests.test_catalog tests.test_agents_docs
            if ($LASTEXITCODE -ne 0) { throw 'smoke tests en rojo' }
            Write-Warn 'suite completa omitida: sin data de usuario ni entrenador; usa -FullTests en una instalacion completa.'
        }
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

function Get-RecommendedSummary {
    $manifest = Read-JsonFile $ModelsManifestPath
    $targets = @(
        $manifest.models | Where-Object { $_.obsolete -ne $true -and $_.required -ne $false }
    )
    $bytes = 0
    foreach ($item in $targets) { $bytes += [long]$item.bytes }
    return [pscustomobject]@{
        Count = $targets.Count
        Gb    = [math]::Round($bytes / 1e9, 1)
    }
}

function Confirm-RecommendedModels {
    if ($SkipModels) { return $false }
    if ($Yes) { return $true }
    $summary = Get-RecommendedSummary
    Write-Host ''
    Write-Host 'Modelos recomendados (Anima + MiniMax H3 + Qwen-Image 2.1 + Upscaler/RIFE + LLM Qwen3.5-9B)' -ForegroundColor Cyan
    Write-Host ("  {0} archivos, ~{1} GB de descarga (SSD SATA recomendado)." -f $summary.Count, $summary.Gb)
    $answer = Read-Host 'Instalar modelos recomendados? [S/n]'
    if ($answer -match '^(n|no)$') {
        Write-Warn 'Sin modelos: la app arrancara sin modelos registrados; ejecuta install.bat cuando quieras.'
        return $false
    }
    return $true
}

function Register-RecommendedModels {
    $recommendedPath = Join-Path $Root 'registry\recommended-v1.json'
    if (-not (Test-Path -LiteralPath $recommendedPath)) { return }
    $recommended = Read-JsonFile $recommendedPath
    $outDir = Join-Path $Root 'data\registry'
    $target = Join-Path $outDir 'models.json'
    $entries = @()
    if (Test-Path -LiteralPath $target) {
        $existing = Read-JsonFile $target
        if ($existing.models) { $entries = @($existing.models) }
    }
    $added = 0
    foreach ($model in @($recommended.models)) {
        if (@($entries | Where-Object { $_.id -eq $model.id }).Count -gt 0) { continue }
        $unet = $model.profile.unet_name
        $candidates = @(
            (Join-Path $ComfyModelsRoot ("checkpoints\{0}" -f $unet)),
            (Join-Path $ComfyModelsRoot ("diffusion_models\{0}" -f $unet)),
            (Join-Path $ComfyModelsRoot ("unet\{0}" -f $unet))
        )
        if (-not (@($candidates | Where-Object { Test-Path -LiteralPath $_ }).Count)) { continue }
        $entries += $model
        $added++
    }
    if ($added -eq 0) { return }
    New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    $payload = [ordered]@{
        version  = 1
        models   = $entries
        _comment = 'Capa de usuario: modelos locales. Editable a mano; install.bat anade los recomendados presentes en disco.'
    }
    $json = $payload | ConvertTo-Json -Depth 12
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($target, $json, $utf8)
    Write-Ok ("data\registry\models.json: {0} modelo(s) recomendado(s) registrados" -f $added)
}

function Install-Ffmpeg {
    if ($SkipFfmpeg) {
        Write-Warn 'SkipFfmpeg: se omite FFmpeg; Timeline/export/fade no estaran disponibles.'
        return
    }
    $ffmpegDir = Join-Path $Root 'tools\ffmpeg'
    $ffmpegExe = Join-Path $ffmpegDir 'ffmpeg.exe'
    $ffprobeExe = Join-Path $ffmpegDir 'ffprobe.exe'
    if ((Test-Path -LiteralPath $ffmpegExe) -and (Test-Path -LiteralPath $ffprobeExe)) {
        try {
            $version = (& $ffmpegExe -version 2>$null | Select-Object -First 1)
            & $ffprobeExe -version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0 -and $version) {
                Write-Ok ("FFmpeg ya instalado: {0}" -f $version)
                return
            }
        } catch {
            Write-Warn 'FFmpeg existente no ejecutable; se reinstala.'
        }
    }

    Write-Step 'FFmpeg/FFprobe portables (tools\ffmpeg)'
    $zip = Join-Path $StateDir 'ffmpeg-n8.1.3-win64-gpl-8.1.zip'
    $extract = Join-Path $StateDir 'ffmpeg-extract'
    $url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-25-13-00/ffmpeg-n8.1.3-24-g92611900bb-win64-gpl-8.1.zip'
    $sha256 = '0ed7e19d34ca040c0179068ccc6cd6d7f2217d2bcbf7604e2225e271e79bee22'
    $bytes = 193050101
    try {
        New-Item -ItemType Directory -Force -Path $StateDir, $ffmpegDir | Out-Null
        Get-VerifiedFile -Url $url -Destination $zip -Sha256 $sha256 -Bytes $bytes
        if (Test-Path -LiteralPath $extract) {
            Remove-Item -LiteralPath $extract -Recurse -Force
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $extract -Force
        $ffmpegSource = Get-ChildItem -LiteralPath $extract -Recurse -Filter 'ffmpeg.exe' -File |
            Select-Object -First 1
        if (-not $ffmpegSource) { throw 'el ZIP no contiene ffmpeg.exe' }
        $ffprobeSource = Join-Path $ffmpegSource.DirectoryName 'ffprobe.exe'
        if (-not (Test-Path -LiteralPath $ffprobeSource)) {
            throw 'el ZIP no contiene ffprobe.exe'
        }
        Copy-Item -LiteralPath $ffmpegSource.FullName -Destination $ffmpegExe -Force
        Copy-Item -LiteralPath $ffprobeSource -Destination $ffprobeExe -Force
        $version = (& $ffmpegExe -version 2>$null | Select-Object -First 1)
        & $ffprobeExe -version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not $version) {
            throw 'los binarios copiados no ejecutan correctamente'
        }
        Write-Ok ("FFmpeg/FFprobe instalados: {0}" -f $version)
    } catch {
        Write-Warn ("No se pudo instalar FFmpeg: {0}" -f $_.Exception.Message)
        Write-Warn 'Timeline/export/fade quedaran deshabilitados hasta instalarlo en tools\ffmpeg.'
        $script:Pending += 'ffmpeg/ffprobe'
    }
}

function Install-Llm {
    if ($SkipLlm) { Write-Warn 'SkipLlm: se omite descarga de LLM'; return }
    $downloadScript = Join-Path $Root 'scripts\download_llm.py'
    if (Test-Path -LiteralPath $downloadScript) {
        Write-Step 'LLM y runtime llama.cpp (scripts\download_llm.py)'
        Invoke-Tool -Label 'download_llm' -Command $VenvPython -ToolArgs @($downloadScript)
    }
}

function Install-Shortcut {
    if ($NoShortcut) { Write-Warn 'NoShortcut: se omite WAIFUSTUDIO.lnk'; return }
    $shortcutScript = Join-Path $Root 'scripts\create_shortcut.ps1'
    if (-not (Test-Path -LiteralPath $shortcutScript)) {
        Write-Warn 'No se encontro scripts\create_shortcut.ps1; no se creo el acceso directo.'
        return
    }
    Write-Step 'acceso directo con icono (WAIFUSTUDIO.lnk)'
    try {
        & $shortcutScript -Root $Root -Quiet
        Write-Ok 'WAIFUSTUDIO.lnk actualizado con static\favicon.ico'
    } catch {
        Write-Warn ("No se pudo crear WAIFUSTUDIO.lnk: {0}" -f $_.Exception.Message)
        $script:Pending += 'acceso directo WAIFUSTUDIO.lnk'
    }
}

Write-Host ''
Write-Host 'WAIFU installer' -ForegroundColor Cyan
Write-Host ("Raiz: {0}" -f $Root)

$environmentScript = Join-Path $Root 'scripts\environment.ps1'
if (Test-Path -LiteralPath $environmentScript) { . $environmentScript }
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:VIRTUAL_ENV = $null
$env:CONDA_PREFIX = $null
$env:CONDA_DEFAULT_ENV = $null
$env:UV_PYTHON_PREFERENCE = 'only-managed'

Invoke-Preflight

Install-Uv
Install-Python
Install-Venv
Install-Ffmpeg
Install-Engine
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'data'), (Join-Path $ComfyRoot 'user\default\workflows') | Out-Null
if ($IncludeTrainer -or ($IncludeOptional -and -not $SkipEngine)) {
    Install-Trainer
}
$installRecommended = Confirm-RecommendedModels
if (-not $installRecommended) { $SkipModels = $true }
Install-Models
Register-RecommendedModels
Install-Llm
Write-Environment
Install-Shortcut
Invoke-FinalVerification

Write-Host ''
if ($script:Pending.Count -gt 0) {
    Write-Warn ("Pendientes de aporte manual: {0}" -f ($script:Pending -join ', '))
    Write-Warn 'El set recomendado incluye 2 modelos Anima de Civitai (age-gate): descargalos a mano, dejando cada archivo en su ruta exacta (ver registry\recommended-v1.json), y re-ejecuta install.bat.'
}
Write-Host 'Instalacion terminada. Siguientes pasos:' -ForegroundColor Green
Write-Host '  1) start.bat        (arranca engine + app y abre la ventana)'
Write-Host '  2) healthcheck.bat  (opcional: diagnostico de rutas/servicios)'
Write-Host '  3) stop.bat         (detiene app + engine)'
Write-Host '  4) LoRAs propias: pestana Imagen > Elegir LoRAs > Gestionar biblioteca'
if ($script:Pending.Count -gt 0) { exit 2 }
exit 0
