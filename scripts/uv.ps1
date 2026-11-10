param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $UvArguments
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$localUv = Join-Path $projectRoot '.tools/bootstrap/bin/uv.exe'
if (Test-Path -LiteralPath $localUv) {
    $uvExecutable = $localUv
} else {
    $uvExecutable = (Get-Command uv -ErrorAction Stop).Source
}
$env:UV_CACHE_DIR = Join-Path $projectRoot '.tools/cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.tools/bin'
& $uvExecutable @UvArguments
exit $LASTEXITCODE
