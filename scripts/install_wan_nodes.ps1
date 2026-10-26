# scripts/install_wan_nodes.ps1
# Instala o sincroniza los nodos ComfyUI para Wan (VideoHelperSuite y MMAudio) en commits exactos.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$appRoot = "E:\IA\WAIFU"
$customNodesDir = Join-Path $appRoot "ComfyUI\custom_nodes"
$pythonExe = Join-Path $appRoot ".venv\Scripts\python.exe"

$repos = @(
    @{
        Name = "ComfyUI-VideoHelperSuite"
        Url = "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"
        Commit = "4d907bee61e92c2e65af3bd6383a4e4d356126d1"
        Path = Join-Path $customNodesDir "ComfyUI-VideoHelperSuite"
    },
    @{
        Name = "ComfyUI-MMAudio"
        Url = "https://github.com/kijai/ComfyUI-MMAudio.git"
        Commit = "8eaeb72edc3aaf2059b57f2d96a1f6f689f19ae2"
        Path = Join-Path $customNodesDir "ComfyUI-MMAudio"
    }
)

function Write-Step {
    param([string]$Message)
    Write-Host "`n>>> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Failure {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

$summary = @()
$hasErrors = $false

if (-not (Test-Path -Path $customNodesDir)) {
    New-Item -ItemType Directory -Path $customNodesDir -Force | Out-Null
}

foreach ($repo in $repos) {
    Write-Step "Procesando $($repo.Name)..."
    $targetDir = $repo.Path
    $targetCommit = $repo.Commit
    $repoUrl = $repo.Url

    try {
        if (-not (Test-Path -Path $targetDir)) {
            Write-Host "Clonando $repoUrl en $targetDir..."
            git clone $repoUrl $targetDir
            if ($LASTEXITCODE -ne 0) {
                throw "Fallo al clonar $($repo.Name)"
            }

            Push-Location $targetDir
            try {
                git checkout $targetCommit
                if ($LASTEXITCODE -ne 0) {
                    throw "Fallo al hacer checkout de $targetCommit en $($repo.Name)"
                }
            }
            finally {
                Pop-Location
            }
        }
        else {
            Write-Host "Directorio existente detectado en $targetDir. Verificando commit actual..."
            Push-Location $targetDir
            try {
                $currentCommit = (git rev-parse HEAD).Trim()
                if ($currentCommit -ne $targetCommit) {
                    Write-Host "Commit actual ($currentCommit) difiere de objetivo ($targetCommit). Sincronizando..."
                    git fetch origin
                    if ($LASTEXITCODE -ne 0) {
                        throw "Fallo al ejecutar git fetch en $($repo.Name)"
                    }
                    git checkout $targetCommit
                    if ($LASTEXITCODE -ne 0) {
                        throw "Fallo al ejecutar git checkout $targetCommit en $($repo.Name)"
                    }
                }
                else {
                    Write-Host "Commit ya coincide con el objetivo: $targetCommit"
                }
            }
            finally {
                Pop-Location
            }
        }

        # Instalar requirements si existen
        $reqFile = Join-Path $targetDir "requirements.txt"
        if (Test-Path -Path $reqFile) {
            Write-Host "Instalando dependencias desde $reqFile..."
            if (-not (Test-Path -Path $pythonExe)) {
                throw "Python virtualenv no encontrado en $pythonExe"
            }

            & $pythonExe -m pip install -r $reqFile
            if ($LASTEXITCODE -ne 0) {
                throw "Fallo al instalar requirements.txt para $($repo.Name)"
            }
        }
        else {
            Write-Host "No se encontro requirements.txt en $($repo.Name), omitiendo instalacion de dependencias."
        }

        $summary += [PSCustomObject]@{
            Nodo = $repo.Name
            Estado = "OK"
            Commit = $targetCommit
            Detalle = "Instalado/verificado correctamente"
        }
        Write-Success "$($repo.Name) procesado exitosamente."
    }
    catch {
        $hasErrors = $true
        $summary += [PSCustomObject]@{
            Nodo = $repo.Name
            Estado = "FAIL"
            Commit = $targetCommit
            Detalle = $_.Exception.Message
        }
        Write-Failure "Error procesando $($repo.Name): $($_.Exception.Message)"
    }
}

Write-Step "Resumen de ejecucion:"
$summary | Format-Table -AutoSize

if ($hasErrors) {
    Write-Failure "La instalacion de nodos finalizo con errores."
    exit 1
}

Write-Success "Todos los nodos de Wan fueron verificados e instalados correctamente."
exit 0
