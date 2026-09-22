$StackRoot = Split-Path -Parent $PSScriptRoot
$env:UV_CACHE_DIR = Join-Path $StackRoot 'cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $StackRoot 'python'
$env:HF_HOME = Join-Path $StackRoot 'cache\huggingface'
$env:TORCH_HOME = Join-Path $StackRoot 'cache\torch'
$env:PIP_CACHE_DIR = Join-Path $StackRoot 'cache\pip'
$env:TEMP = Join-Path $StackRoot 'tmp'
$env:TMP = $env:TEMP
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
foreach ($dir in @($env:UV_CACHE_DIR,$env:UV_PYTHON_INSTALL_DIR,$env:HF_HOME,$env:TORCH_HOME,$env:PIP_CACHE_DIR,$env:TEMP)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
