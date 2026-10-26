#Requires -Version 5.1
<#
.SYNOPSIS
    Descarga los modelos del manifiesto Wan 2.2 verificando integridad (bytes y SHA256).
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# 1. Comprobar que curl.exe exista
$curlPath = Get-Command curl.exe -ErrorAction SilentlyContinue
if (-not $curlPath) {
    Write-Error "ERROR: curl.exe no fue encontrado en el PATH del sistema. Es necesario para realizar las descargas."
    exit 1
}

# 2. Rutas base y manifiesto
$root = Split-Path $PSScriptRoot -Parent
$manifestPath = Join-Path $root 'install\manifest\manifest.wan.json'

if (-not (Test-Path -LiteralPath $manifestPath)) {
    Write-Error "ERROR: No se encontro el archivo de manifiesto en: $manifestPath"
    exit 1
}

try {
    $manifestRaw = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
    $manifest = $manifestRaw | ConvertFrom-Json
} catch {
    Write-Error "ERROR: No se pudo leer o parsear el archivo de manifiesto: $_"
    exit 1
}

if (-not $manifest.models -or $manifest.models.Count -eq 0) {
    Write-Host "No se encontraron modelos para descargar en el manifiesto."
    exit 0
}

Write-Host "============================================================"
Write-Host "  Descarga de Modelos Wan 2.2 - WAIFU"
Write-Host "============================================================"
Write-Host "Directorio base: $root"
Write-Host "Total de modelos en manifiesto: $($manifest.models.Count)"
Write-Host "============================================================`n"

$totalCount = $manifest.models.Count
$skippedCount = 0
$downloadedCount = 0
$failedCount = 0

foreach ($entry in $manifest.models) {
    $targetDir = Join-Path $root "ComfyUI\models\$($entry.subdir)"
    $finalPath = Join-Path $targetDir $entry.filename
    $partPath  = "$finalPath.part"

    Write-Host "------------------------------------------------------------"
    Write-Host "Modelo: $($entry.id)"
    Write-Host "Destino: $finalPath"

    # Asegurar directorio de destino con New-Item -Force
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    # Comprobar si el archivo final ya existe y verificar SHA256
    if (Test-Path -LiteralPath $finalPath) {
        $finalItem = Get-Item -LiteralPath $finalPath
        if ($null -ne $entry.bytes -and $finalItem.Length -eq [int64]$entry.bytes) {
            Write-Host "  Calculando SHA256 existente..."
            $existingHash = (Get-FileHash -LiteralPath $finalPath -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($existingHash -eq $entry.sha256.ToLowerInvariant()) {
                Write-Host "  [SALTADO] El archivo ya existe y el hash SHA256 coincide."
                $skippedCount++
                continue
            } else {
                Write-Warning "  El archivo existe pero el hash no coincide. Procediendo a descargar nueva version en .part..."
            }
        } else {
            Write-Warning "  El archivo existe pero el tamano en bytes no coincide. Procediendo a descargar en .part..."
        }
    }

    # Descargar a <archivo>.part con soporte de reanudacion (-C -)
    Write-Host "  Iniciando descarga a: $partPath"
    & curl.exe -L --fail -C - -o $partPath $entry.url
    $curlExitCode = $LASTEXITCODE

    if ($curlExitCode -ne 0) {
        Write-Error "ERROR: curl fallo con codigo de salida $curlExitCode al descargar $($entry.id)."
        $failedCount++
        exit 1
    }

    if (-not (Test-Path -LiteralPath $partPath)) {
        Write-Error "ERROR: El archivo temporal no existe tras la descarga: $partPath"
        $failedCount++
        exit 1
    }

    $partItem = Get-Item -LiteralPath $partPath

    # 1. Verificar Length contra bytes
    if ($null -ne $entry.bytes -and $partItem.Length -ne [int64]$entry.bytes) {
        Write-Error "ERROR de integridad: Tamano esperado $($entry.bytes) bytes, pero se obtuvieron $($partItem.Length) bytes en $partPath."
        $failedCount++
        exit 1
    }

    # 2. Verificar SHA256
    Write-Host "  Verificando SHA256 del archivo descargado..."
    $computedHash = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedHash = $entry.sha256.ToLowerInvariant()

    if ($computedHash -ne $expectedHash) {
        Write-Error "ERROR de integridad: SHA256 no coincide para $($entry.filename).`nEsperado: $expectedHash`nObtenido: $computedHash`nSe conserva $partPath para depuracion."
        $failedCount++
        exit 1
    }

    # 3. Mover a archivo final
    Move-Item -LiteralPath $partPath -Destination $finalPath -Force
    Write-Host "  [OK] Descargado y verificado correctamente."
    $downloadedCount++
}

Write-Host "`n============================================================"
Write-Host "                      RESUMEN TOTAL"
Write-Host "============================================================"
Write-Host "Total modelos  : $totalCount"
Write-Host "Descargados    : $downloadedCount"
Write-Host "Saltados       : $skippedCount"
Write-Host "Fallidos       : $failedCount"
Write-Host "============================================================"

if ($failedCount -gt 0) {
    exit 1
}

exit 0
